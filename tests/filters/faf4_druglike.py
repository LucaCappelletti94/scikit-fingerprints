import numpy as np
import pytest

from skfp.filters import FAF4DruglikeFilter


@pytest.fixture
def smiles_passing_faf4_druglike() -> list[str]:
    return [
        # paracetamol
        "CC(=O)Nc1ccc(O)cc1",
        # Ibuprofen
        "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O",
        # caffeine
        "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
        # nicotine
        "c1ncccc1[C@@H]2CCCN2C",
    ]


@pytest.fixture
def smiles_failing_faf4_druglike() -> list[str]:
    # flake8: noqa: E501
    return [
        # Rinfampin
        r"CN1CCN(CC1)/N=C/c2c(O)c3c5C(=O)[C@@]4(C)O/C=C/[C@H](OC)[C@@H](C)[C@@H](OC(C)=O)[C@H](C)[C@H](O)[C@H](C)[C@@H](O)[C@@H](C)\C=C\C=C(\C)C(=O)Nc2c(O)c3c(O)c(C)c5O4",
        # Probucol
        "S(c1cc(c(O)c(c1)C(C)(C)C)C(C)(C)C)C(Sc2cc(c(O)c(c2)C(C)(C)C)C(C)(C)C)(C)C",
        # Kanamycin
        "O([C@@H]2[C@@H](O)[C@H](O[C@H]1O[C@H](CN)[C@@H](O)[C@H](O)[C@H]1O)[C@@H](N)C[C@H]2N)[C@H]3O[C@@H]([C@@H](O)[C@H](N)[C@H]3O)CO",
    ]
    # flake8: noqa


@pytest.fixture
def smiles_passing_one_violation_faf4_druglike() -> list[str]:
    return [
        # Aliskerin
        "O=C(N)C(C)(C)CNC(=O)[C@H](C(C)C)C[C@H](O)[C@@H](N)C[C@@H](C(C)C)Cc1cc(OCCCOC)c(OC)cc1",
    ]


def test_mols_passing_faf4_druglike(smiles_passing_faf4_druglike):
    mol_filter = FAF4DruglikeFilter()
    smiles_filtered = mol_filter.transform(smiles_passing_faf4_druglike)
    assert all(isinstance(x, str) for x in smiles_filtered)
    assert len(smiles_filtered) == len(smiles_passing_faf4_druglike)


def test_mols_partially_passing_faf4_druglike(
    smiles_passing_one_violation_faf4_druglike,
):
    mol_filter = FAF4DruglikeFilter(allow_one_violation=True)
    smiles_filtered = mol_filter.transform(smiles_passing_one_violation_faf4_druglike)
    assert all(isinstance(x, str) for x in smiles_filtered)
    assert len(smiles_filtered) == len(smiles_passing_one_violation_faf4_druglike)


def test_mols_failing_faf4_druglike(smiles_failing_faf4_druglike):
    mol_filter = FAF4DruglikeFilter()
    smiles_filtered = mol_filter.transform(smiles_failing_faf4_druglike)
    assert all(isinstance(x, str) for x in smiles_filtered)
    assert len(smiles_filtered) == 0


def test_faf4_druglike_return_indicators(
    smiles_passing_faf4_druglike,
    smiles_failing_faf4_druglike,
    smiles_passing_one_violation_faf4_druglike,
):
    all_smiles = (
        smiles_passing_faf4_druglike
        + smiles_failing_faf4_druglike
        + smiles_passing_one_violation_faf4_druglike
    )

    mol_filter = FAF4DruglikeFilter(return_indicators=True)
    filter_indicators = mol_filter.transform(all_smiles)
    expected_indicators = np.array(
        [True] * len(smiles_passing_faf4_druglike)
        + [False] * len(smiles_failing_faf4_druglike)
        + [False] * len(smiles_passing_one_violation_faf4_druglike),
        dtype=bool,
    )
    assert np.array_equal(filter_indicators, expected_indicators)

    mol_filter = FAF4DruglikeFilter(allow_one_violation=True, return_indicators=True)
    filter_indicators = mol_filter.transform(all_smiles)
    expected_indicators = np.array(
        [True] * len(smiles_passing_faf4_druglike)
        + [False] * len(smiles_failing_faf4_druglike)
        + [True] * len(smiles_passing_one_violation_faf4_druglike),
        dtype=bool,
    )
    assert np.array_equal(filter_indicators, expected_indicators)


def test_faf4_druglike_parallel(smiles_list):
    mol_filter = FAF4DruglikeFilter()
    mols_filtered_sequential = mol_filter.transform(smiles_list)

    mol_filter = FAF4DruglikeFilter(n_jobs=-1, batch_size=1)
    mols_filtered_parallel = mol_filter.transform(smiles_list)

    assert mols_filtered_sequential == mols_filtered_parallel