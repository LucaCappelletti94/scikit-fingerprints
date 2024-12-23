import hashlib
import itertools
import struct
from collections import defaultdict
from collections.abc import Sequence
from numbers import Integral
from typing import Optional, Union

import numpy as np
from datasketch import MinHash
from rdkit.Chem import Mol, MolToSmiles, PathToSubmol
from rdkit.Chem.rdmolops import FindAtomEnvironmentOfRadiusN, GetDistanceMatrix
from scipy.sparse import csr_array
from sklearn.utils._param_validation import Interval, StrOptions

from skfp.bases import BaseFingerprintTransformer
from skfp.utils import ensure_mols


class MAPFingerprint(BaseFingerprintTransformer):
    """
    MinHashed Atom Pair fingerprint (MAP).

    Implementation is based on the official MAP4 paper and code [1]_ [2]_. This is a
    hashed fingerprint, using the ideas from Atom Pair and SECFP fingerprints.

    It computes fragments based on pairs of atoms, using circular
    substructures around each atom represented with SMILES (like SECFP) and length
    of shortest path between them (like Atom Pair), and then hashes the resulting
    triplet using MinHash fingerprint.

    Subgraphs are created around each atom with increasing radius, starting
    with just an atom itself. It is then transformed into a canonical SMILES.
    In each iteration, it is increased by another atom (one "hop" on the graph).

    For each pair of atoms, length of the shortest path is created. Then, for
    each radius from 1 up to the given maximal radius, the triplet is created:
    (atom 1 SMILES, shortest path length, atom 2 SMILES). They are then hashed
    using MinHash algorithm.

    Parameters
    ----------
    fp_size : int, default=2048
        Size of output vectors. Depending on the ``variant`` argument, those are either
        raw hashes, bits, or counts. Must be positive.

    radius : int, default=2
        Number of iterations performed, i.e. maximum radius of resulting subgraphs.
        Another common notation uses diameter, therefore MAP4 has radius 2.

    variant : {"raw_hashes", "bit", "count"}, default="bit"
        Which variant to fingerprint to use. ``"raw_hashes"`` returns MinHash values.
        ``"bit"`` folds values into binary vector, and ``"count"`` uses folding with
        counting.

    sparse : bool, default=False
        Whether to return dense NumPy array, or sparse SciPy CSR array.

    n_jobs : int, default=None
        The number of jobs to run in parallel. :meth:`transform` is parallelized
        over the input molecules. ``None`` means 1 unless in a
        :obj:`joblib.parallel_backend` context. ``-1`` means using all processors.
        See Scikit-learn documentation on ``n_jobs`` for more details.

    batch_size : int, default=None
        Number of inputs processed in each batch. ``None`` divides input data into
        equal-sized parts, as many as ``n_jobs``.

    verbose : int or dict, default=0
        Controls the verbosity when computing fingerprints.
        If a dictionary is passed, it is treated as kwargs for ``tqdm()``,
        and can be used to control the progress bar.

    Attributes
    ----------
    n_features_out : int
        Number of output features. Equal to ``fp_size``.

    requires_conformers : bool = False
        This fingerprint uses only 2D molecular graphs and does not require conformers.

    See Also
    --------
    :class:`AtomPairFingerprint` : Related fingerprint, which uses atom invariants and
        folding.

    :class:`SECFPFingerprint` : Related fingerprint, which only uses SMILES of circular
        subgraph around each atom.

    References
    ----------
    .. [1] `Alice Capecchi, Daniel Probst and Jean-Louis Reymond
        "One molecular fingerprint to rule them all: drugs, biomolecules, and the metabolome"
        J Cheminform 12, 43 (2020)
        <https://jcheminf.biomedcentral.com/articles/10.1186/s13321-020-00445-4>`_

    .. [2] `https://github.com/reymond-group/map4`

    Examples
    --------
    >>> from skfp.fingerprints import MAPFingerprint
    >>> smiles = ["O", "CC", "[C-]#N", "CC=O"]
    >>> fp = MAPFingerprint()
    >>> fp
    MAPFingerprint()

    >>> fp.transform(smiles)
    array([[0, 0, 0, ..., 0, 0, 0],
           [0, 0, 0, ..., 0, 0, 0],
           [0, 0, 0, ..., 0, 0, 0],
           [0, 0, 0, ..., 0, 0, 0]], dtype=uint8)
    """

    _parameter_constraints: dict = {
        **BaseFingerprintTransformer._parameter_constraints,
        "fp_size": [Interval(Integral, 1, None, closed="left")],
        "radius": [Interval(Integral, 0, None, closed="left")],
        "variant": [StrOptions({"bit", "count", "raw_hashes"})],
    }

    def __init__(
        self,
        fp_size: int = 1024,
        radius: int = 2,
        variant: str = "bit",
        sparse: bool = False,
        n_jobs: Optional[int] = None,
        batch_size: Optional[int] = None,
        verbose: Union[int, dict] = 0,
        random_state: Optional[int] = 0,
    ):
        super().__init__(
            n_features_out=fp_size,
            sparse=sparse,
            n_jobs=n_jobs,
            batch_size=batch_size,
            verbose=verbose,
            random_state=random_state,
        )
        self.fp_size = fp_size
        self.radius = radius
        self.variant = variant

    def _calculate_fingerprint(
        self, X: Sequence[Union[str, Mol]]
    ) -> Union[np.ndarray, csr_array]:
        X = ensure_mols(X)
        X = np.stack(
            [self._calculate_single_mol_fingerprint(mol) for mol in X], dtype=int
        )

        if self.variant == "bit":
            X = (X > 0).astype(np.uint8)
        elif self.variant == "count":
            X = X.astype(np.uint32)

        return csr_array(X) if self.sparse else np.array(X)

    def _calculate_single_mol_fingerprint(self, mol: Mol) -> np.ndarray:
        atoms_envs = self._get_atom_envs(mol)
        shingles = self._get_atom_pair_shingles(mol, atoms_envs)

        if self.variant == "raw_hashes":
            encoder = MinHash(num_perm=self.fp_size, seed=self.random_state)
            encoder.update_batch(shingles)
            fp = encoder.digest()
        else:
            # bit/count folded version from original MAP4 and MHFP implementation
            hashes = [self._get_hash(shingle) for shingle in shingles]
            bits = [hash_val % self.fp_size for hash_val in hashes]
            fp = np.bincount(bits, minlength=self.fp_size)

        return fp

    def _get_atom_envs(self, mol: Mol) -> dict[int, list[Optional[str]]]:
        """
        For each atom get its environment, i.e. radius-hop neighborhood.
        """
        atoms_env = defaultdict(list)
        for atom in mol.GetAtoms():
            idx = atom.GetIdx()
            atom_envs = [
                self._find_neighborhood(mol, idx, r) for r in range(1, self.radius + 1)
            ]
            atoms_env[idx].extend(atom_envs)

        return atoms_env

    def _find_neighborhood(
        self, mol: Mol, atom_idx: int, n_radius: int
    ) -> Optional[str]:
        """
        Get the radius-hop neighborhood for a given atom. If there is no neighborhood
        of a given radius, e.g. 2-hop neighborhood for [Li]F with just two atoms,
        returns None.
        """
        try:
            env = FindAtomEnvironmentOfRadiusN(mol, atom_idx, n_radius)
        except ValueError:
            # "bad atom index" error happens if radius is larger than possible
            return None

        atom_map: dict[int, int] = dict()

        submol = PathToSubmol(mol, env, atomMap=atom_map)

        if atom_idx in atom_map:
            return MolToSmiles(
                submol,
                rootedAtAtom=atom_map[atom_idx],
                canonical=True,
                isomericSmiles=False,
            )
        else:
            return None

    def _get_atom_pair_shingles(self, mol: Mol, atoms_envs: dict) -> list[bytes]:
        """
        Gets a list of atom molecular shingles - circular structures around atom pairs,
        written as SMILES, separated by the bond distance between the two atoms along the
        shortest path.
        """
        shingles = []
        distance_matrix = GetDistanceMatrix(mol)
        num_atoms = mol.GetNumAtoms()
        shingle_dict: dict[str, int] = defaultdict(int)

        # Iterate through all pairs of atoms and radius. Shingles are stored in format:
        # (radius i neighborhood of atom A) | (distance between atoms A and B) | (radius i neighborhood of atom B)
        #
        # If we want to count the shingles, we increment their value in shingle_dict
        # After nested for-loop, all shingles, with their respective counts, will be added to atom_pairs list.
        for idx_1, idx_2 in itertools.combinations(range(num_atoms), 2):
            # distance_matrix consists of floats as integers, so they need to be converted to integers first
            dist = str(int(distance_matrix[idx_1][idx_2]))
            env_a = atoms_envs[idx_1]
            env_b = atoms_envs[idx_2]

            for i in range(self.radius):
                env_a_radius = env_a[i]
                env_b_radius = env_b[i]

                # can be None if we couldn't get atom neighborhood of given radius
                if not env_a_radius or not env_b_radius:
                    continue

                ordered = sorted([env_a_radius, env_b_radius])
                shingle = f"{ordered[0]}|{dist}|{ordered[1]}"

                if self.variant == "count":
                    shingle_dict[shingle] += 1
                else:
                    shingles.append(shingle)

        if self.variant == "count":
            # shingle in format:
            # (radius i neighborhood of atom A) | (distance between atoms A and B) | \
            # (radius i neighborhood of atom B) | (shingle count)
            shingle_count = [
                f"{shingle}|{shingle_count}"
                for shingle, shingle_count in shingle_dict.items()
            ]
            shingles.extend(shingle_count)

        # convert strings to bytes for hashing
        shingles = [shingle.encode() for shingle in shingles]

        return shingles

    def _get_hash(self, shingle: bytes) -> int:
        hash_bytes = hashlib.sha1(shingle, usedforsecurity=False).digest()
        hash_value = struct.unpack("<I", hash_bytes[:4])[0]
        return hash_value
