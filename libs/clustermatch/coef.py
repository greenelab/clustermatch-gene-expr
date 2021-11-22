"""
Contains function that implement the Clustermatch coefficient
(https://doi.org/10.1093/bioinformatics/bty899).
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import numpy as np
from numpy.typing import NDArray
from numba import njit, get_num_threads
from numba.typed import List

from clustermatch.pytorch.core import unravel_index_2d
from clustermatch.sklearn.metrics import adjusted_rand_index as ari
from clustermatch.scipy.stats import rank


@njit(cache=True)
def _get_perc_from_k(k: int) -> list[float]:
    """
    It returns the percentiles (from 0.0 to 1.0) that separate the data into k
    clusters. For example, if k=2, it returns [0.5]; if k=4, it returns [0.25,
    0.50, 0.75].

    Args:
        k: number of clusters. If less than 2, the function returns an empty
            list.

    Returns:
        A list of percentiles (from 0.0 to 1.0).
    """
    return [(1.0 / k) * i for i in range(1, k)]


@njit(cache=True)
def run_quantile_clustering(data: NDArray, k: int) -> NDArray[np.int16]:
    """
    Performs a simple quantile clustering on one dimensional data (1d). Quantile
    clustering is defined as the procedure that forms clusters in 1d data by
    separating objects using quantiles (for instance, if the median is used, two
    clusters are generated with objects separated by the median). In the case
    data contains all the same values (zero variance), this implementation can
    return less clusters than specified with k.

    Args:
        data: a 1d numpy array with numerical values.
        k: the number of clusters to split the data into.

    Returns:
        A 1d array with the data partition.
    """
    data_sorted = np.argsort(data, kind="quicksort")
    data_rank = rank(data, data_sorted)
    data_perc = data_rank / data_rank.max()

    percentiles = [0.0] + _get_perc_from_k(k) + [1.0]

    cut_points = np.searchsorted(data_perc[data_sorted], percentiles, side="right")

    current_cluster = 0
    part = np.zeros(data.shape, dtype=np.int16) - 1

    for i in range(len(cut_points) - 1):
        lim1 = cut_points[i]
        lim2 = cut_points[i + 1]

        part[data_sorted[lim1:lim2]] = current_cluster
        current_cluster += 1

    return part


@njit(cache=True)
def _get_range_n_clusters(
    n_features: int, internal_n_clusters: Iterable[int] = None
) -> NDArray[np.uint8]:
    """
    Given the number of features it returns a tuple of k values to cluster those
    features into. By default, it generates a tuple of k values from 2 to
    int(np.round(np.sqrt(n_features))) (inclusive). For example, for 25 features,
    it will generate this tuple: (2, 3, 4, 5).

    Args:
        n_features: a positive number representing the number of features that
            will be clustered into different groups/clusters.
        internal_n_clusters: it allows to force a different list of clusters. It
            must be a list of integers. Repeated or invalid values will be dropped,
            such as values lesser than 2 (a singleton partition is not allowed).

    Returns:
        A numpy array with integer values representing numbers of clusters.
    """

    if internal_n_clusters is not None:
        # remove k values that are invalid
        clusters_range_list = list(
            set([int(x) for x in internal_n_clusters if 1 < x < n_features])
        )
    else:
        # default behavior if no internal_n_clusters is given: return range from
        # 2 to sqrt(n_features)
        n_sqrt = int(np.round(np.sqrt(n_features)))
        n_sqrt = min((n_sqrt, 10))
        clusters_range_list = list(range(2, n_sqrt + 1))

    return np.array(clusters_range_list, dtype=np.uint16)


@njit(cache=True, nogil=True)
def _get_parts(data: NDArray, range_n_clusters: tuple[int]) -> NDArray[np.int16]:
    """
    Given a 1d data array, it computes a partition for each k value in the given
    range of clusters. This function only supports numerical data, and it
    always runs run_run_quantile_clustering with the different k values.
    If partitions with only one cluster are returned (singletons), then the
    returned array will have negative values.

    Args:
        data: a 1d data vector. It is assumed that there are no nans.
        range_n_clusters: a tuple with the number of clusters.

    Returns:
        A numpy array with shape (number of clusters, data rows) with
        partitions of data.
    """
    parts = np.zeros((len(range_n_clusters), data.shape[0]), dtype=np.int16)

    for idx in range(len(range_n_clusters)):
        k = range_n_clusters[idx]
        parts[idx] = run_quantile_clustering(data, k)

    # remove singletons
    partitions_ks = np.array([len(np.unique(p)) for p in parts])
    parts[partitions_ks == 1, :] = -1

    return parts


def cdist_parts(x: NDArray, y: NDArray, n_threads: int = 1) -> NDArray[np.float]:
    """
    It implements the same functionality in scipy.spatial.distance.cdist but
    for clustering partitions, and instead of a distance it returns the adjusted
    Rand index (ARI). In other words, it mimics this function call:

        cdist(x, y, metric=ari)

    Args:
        x: a 2d array with m_x clustering partitions in rows and n objects in
          columns.
        y: a 2d array with m_y clustering partitions in rows and n objects in
          columns.
        n_threads: TODO

    Returns:
        A 2d array with m_x rows and m_y columns and the ARI between each
        partition pair. Each ij entry is equal to ari(x[i], y[j]) for each i
        and j.
    """
    res = np.zeros((x.shape[0], y.shape[0]))

    with ThreadPoolExecutor(max_workers=n_threads) as executor:
        inputs = range(res.shape[0])

        def run(i):
            return np.array([ari(x[i], y[j]) for j in range(res.shape[1])])

        for idx, ps in zip(inputs, executor.map(run, inputs)):
            res[idx, :] = ps

    return res


@njit(cache=True, nogil=True)
def get_coords_from_index(n_obj: int, idx: int) -> tuple[int]:
    """
    Given the number of objects and and index, it returns the row/column
    position of the pairwise matrix. For example, if there are n_obj objects
    (such as genes), a condensed 1d array can be created with pairwise
    comparisons between genes, as well as a squared symmetric matrix. This
    function receives the number of objects and the index of the condensed
    array, and returns the coordiates of the squared symmetric matrix.

    Args:
        n_obj: the number of objects.
        idx: the index of the condensed pairwise array across all n_obj objects.

    Returns
        A tuple (i, j) with the coordinates of the squared symmetric matrix
        equivalent to the condensed array.
    """
    b = 1 - 2 * n_obj
    x = np.floor((-b - np.sqrt(b ** 2 - 8 * idx)) / 2)
    y = idx + x * (b + x + 2) / 2 + 1
    return int(x), int(y)


def _cm(
    x: NDArray, y: NDArray = None, internal_n_clusters: Iterable[int] = None
) -> tuple[NDArray[np.float], NDArray[np.uint64], NDArray[np.int16]]:
    """
    This is the main function that computes the Clustermatch coefficient between
    two arrays. This implementation only supports numerical data for
    optimization purposes, but the original implementation can also work with
    categorical data (https://github.com/sinc-lab/clustermatch).

    Args:
        x: an 1d or 2d numerical array with the data. NaN are not supported.
          If it is 2d, then the coefficient is computed for each pair of rows.
        y: an optional 1d numerical array. If x is 1d and y is given, it computes
          the coefficient between x and y.
        internal_n_clusters: a list of integer values indicating the number of
          clusters used to split x and y.

    Returns:
        A tuple containing three arrays:

        cm_values: a 1d condensed array of pairwise coefficients. It has size
            (n * (n - 1)) / 2, where n is the number of columns in x and y (for
            example, the number of samples for genes).
            The Clustermatch coefficient is always between 0 and 1 (inclusive).
            If any of the two variables being compared has no variation (all
            values are the same), the coefficient is not defined (np.nan).

        max_parts: an array with n * (n - 1)) / 2 rows (one for each object
            pair) and two columns. It has the indexes pointing to the partitions
            (parts, see below) for each object that maximized the ARI. If
            cm_values[idx} is nan, then max_parts[idx] will be meaningless.

        parts: a 3d array that contains all the internal partitions generated
            for each object in data. parts[i] has the partitions for object i,
            whereas parts[i,j] accesses the partition j generated for object i.
            The third dimension is the number of columns in X. For example, if
            you want to access the pair of partitions that maximized the
            Clustermatch coefficient given x and y (a pair of objects), then
            max_parts[0] and max_parts[1] have the partition indexes for parts,
            respectively: parts[0][max_parts[0]] points to the partition for x,
            and parts[1][max_parts[1]] points to the partition for y.
    """
    if x.ndim == 1 and y is not None:
        assert x.shape == y.shape
        X = np.zeros((2, x.shape[0]))
        X[0, :] = x
        X[1, :] = y
    elif x.ndim == 2:
        X = x
    else:
        raise ValueError("Wrong combination of parameters x and y")

    default_n_threads = get_num_threads()

    # get matrix of partitions for each object pair
    range_n_clusters = _get_range_n_clusters(X.shape[1], internal_n_clusters)

    # store a set of partitions per row (object) in X as a multidimensional
    # array:
    #  - 1st dim: number of objects/rows in X
    #  - 2nd dim: number of partitions per object
    #  - 3rd dim: number of features per object (columns in X)
    parts = np.zeros(
        (X.shape[0], range_n_clusters.shape[0], X.shape[1]), dtype=np.int16
    )

    # pre-compute the internal partitions for each object in parallel
    with ThreadPoolExecutor(max_workers=default_n_threads) as executor:
        inputs = range(X.shape[0])

        def run(i):
            return _get_parts(X[i], range_n_clusters)

        for idx, ps in zip(inputs, executor.map(run, inputs)):
            parts[idx] = ps

    # cm_values stores the clusermatch coefficients
    n = X.shape[0]
    out_size = (n * (n - 1)) // 2
    cm_values = np.empty(out_size)
    cm_values[:] = np.nan

    # for each object pair being compared, max_parts has the indexes of the
    # partitions that maximimized the ARI
    max_parts = np.zeros((out_size, 2), dtype=np.uint64)

    # Below, there are two layers of parallelism: 1) parallel execution across
    # object pairs (first for loop with prange) and 2) the cdist_parts
    # function, which also runs several threads to compare partitions with ari.
    # In 2) we need to disable parallelization in case len(cm_values) > 1,
    # otherwise these two layers are not "serialized" (they spawn
    # NUMBA_NUM_THREADS threads each for some reason).
    # TODO: this should probably be reported in numba as a potential bug
    cdist_parts_n_threads = default_n_threads if cm_values.shape[0] == 1 else 1

    with ThreadPoolExecutor(max_workers=default_n_threads) as executor:
        inputs = range(cm_values.shape[0])

        def run(idx):
            i, j = get_coords_from_index(n, idx)

            # get partitions for the pair of objects
            obji_parts, objj_parts = parts[i], parts[j]

            max_ari = np.nan
            max_idx = int(0), int(0)

            # compute ari only if partitions are not marked as "missing"
            # (negative values)
            if obji_parts[0, 0] >= -1 and objj_parts[0, 0] >= 0:
                comp_values = cdist_parts(obji_parts, objj_parts, cdist_parts_n_threads)
                max_flat_idx = comp_values.argmax()

                max_idx = unravel_index_2d(max_flat_idx, comp_values.shape)
                max_ari = np.max((comp_values[max_idx], 0.0))

            return max_ari, max_idx

        for idx, (max_ari, max_idx) in zip(inputs, executor.map(run, inputs)):
            cm_values[idx] = max_ari
            max_parts[idx, :] = max_idx

    # # TODO add threading here
    # for idx in range(cm_values.shape[0]):
    #     i, j = get_coords_from_index(n, idx)
    #
    #     # get partitions for the pair of objects
    #     obji_parts, objj_parts = parts[i], parts[j]
    #
    #     if obji_parts[0, 0] == -1 or objj_parts[0, 0] == -1:
    #         cm_values[idx] = np.nan
    #     else:
    #         # TODO add threading here, and nogil to cdist_parts
    #         comp_values = cdist_parts(obji_parts, objj_parts, cdist_parts_n_threads)
    #         max_flat_idx = comp_values.argmax()
    #         max_idx = unravel_index_2d(max_flat_idx, comp_values.shape)
    #
    #         max_ari = comp_values[max_idx]
    #         max_parts[idx, :] = max_idx
    #
    #         cm_values[idx] = max_ari if max_ari >= 0.0 else 0.0

    return cm_values, max_parts, parts


def to_numpy(x):
    """
    TODO: update
    """
    if x is None:
        return x

    func = getattr(x, "to_numpy", None)
    if not callable(func):
        return x

    return x.to_numpy()


def cm(
    x: NDArray,
    y: NDArray = None,
    internal_n_clusters: Iterable[int] = None,
    return_parts: bool = False,
):
    """
    This function is a wrapper over _cm, a not-jitted (numba) function that can
    return different value types according to the input given (this is a problem
    with numba).

    Args:
        x: same as in _cm function.
        y: same as in _cm function.
        internal_n_clusters: same as in _cm function.
        return_parts: TODO finish

    Returns:
        TODO: UPDATE

        If x is 2d, then a np.ndarray of size n x n is returned with the
        coefficient value, where n is the number of rows in x. If only a single
        coefficient was computed (for example, x and y were given), then a
        single scalar is returned.
    """

    # convert list to numba.types.List, since reflection is deprecated:
    # https://numba.pydata.org/numba-doc/latest/reference/deprecation.html#deprecation-of-reflection-for-list-and-set-types
    n_clusters = None

    x = to_numpy(x)
    y = to_numpy(y)

    if internal_n_clusters is not None:
        n_clusters = List()
        for k in internal_n_clusters:
            n_clusters.append(k)

    # run optimized _cm function
    cm_values, max_parts, parts = _cm(x, y, n_clusters)

    # return an array of values or a single scalar
    if cm_values.shape[0] == 1:
        if return_parts:
            return cm_values[0], max_parts[0], parts
        else:
            return cm_values[0]

    if return_parts:
        return cm_values, max_parts, parts
    else:
        return cm_values
