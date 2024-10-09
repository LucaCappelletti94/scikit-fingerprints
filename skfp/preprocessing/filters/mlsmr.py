from typing import Optional, Union

from rdkit.Chem import FilterCatalog, Mol
from rdkit.Chem.rdfiltercatalog import FilterCatalogParams

from skfp.bases.base_filter import BaseFilter
from skfp.utils import TQDMSettings


class MLSMRFilter(BaseFilter):
    """
    MLSMR filter.

    NIH Molecular Libraries Small Molecule Repository (MLSMR) "Excluded Functionality
    Filters". MLSMR was a library of diverse small molecules (now discontinued).

    Filter origin and rules rationale are currently unknown, and there seems to be no
    literature reference. Rule definitions are available in the RDKit code [1]_.

    Parameters
    ----------
    allow_one_violation : bool, default=False
        Whether to allow violating one of the rules for a molecule, which makes the
        filter less restrictive.

    n_jobs : int, default=None
        The number of jobs to run in parallel. :meth:`transform_x_y` and
        :meth:`transform` are parallelized over the input molecules. ``None`` means 1
        unless in a :obj:`joblib.parallel_backend` context. ``-1`` means using all
        processors. See Scikit-learn documentation on ``n_jobs`` for more details.

    batch_size : int, default=None
        Number of inputs processed in each batch. ``None`` divides input data into
        equal-sized parts, as many as ``n_jobs``.

    verbose : int or TQDMSettings, default=0
        Controls the verbosity when generating conformers.

    References
    ----------
    .. [1] `RDKit MLSMR filter definitions
        <https://github.com/rdkit/rdkit/blob/e4f4644a89d6446ddebda0bf396fa4335324c41c/Code/GraphMol/FilterCatalog/chembl_mlsmr.in>`_

    Examples
    --------
    >>> from skfp.preprocessing import MLSMRFilter
    >>> smiles = ["C", "O", "OP(=O)(O)O"]
    >>> filt = MLSMRFilter()
    >>> filt
    MLSMRFilter()

    >>> filtered_mols = filt.transform(smiles)
    >>> filtered_mols
    ['C', 'O']
    """

    def __init__(
        self,
        allow_one_violation: bool = False,
        return_indicators: bool = False,
        n_jobs: Optional[int] = None,
        batch_size: Optional[int] = None,
        verbose: Union[int, TQDMSettings] = 0,
    ):
        super().__init__(
            allow_one_violation=allow_one_violation,
            return_indicators=return_indicators,
            n_jobs=n_jobs,
            batch_size=batch_size,
            verbose=verbose,
        )
        self._filters = self._load_filters()

    def _load_filters(self) -> FilterCatalog:
        filter_rules = FilterCatalogParams.FilterCatalogs.CHEMBL_MLSMR
        params = FilterCatalog.FilterCatalogParams()
        params.AddCatalog(filter_rules)
        filters = FilterCatalog.FilterCatalog(params)
        return filters

    def _apply_mol_filter(self, mol: Mol) -> bool:
        errors = len(self._filters.GetMatches(mol))
        return not errors or (self.allow_one_violation and errors == 1)
