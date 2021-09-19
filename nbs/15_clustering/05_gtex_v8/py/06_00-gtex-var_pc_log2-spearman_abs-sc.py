# -*- coding: utf-8 -*-
# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: all,-execution,-papermill,-trusted
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.11.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown] tags=[]
# # Description

# %% [markdown] tags=[]
# It runs a Spectral Clustering (SC) algorithm on the similarity matrix generated by the correlation method specified below (under `Settings`). It saves the set of clustering solutions (called "ensemble") into a pandas dataframe.

# %% [markdown] tags=[]
# # Modules loading

# %% tags=[]
import numpy as np
import pandas as pd
from sklearn.cluster import SpectralClustering
from sklearn.metrics import silhouette_score
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm

from clustermatch import conf
from clustermatch.utils import simplify_string
from clustermatch.clustering import generate_ensemble

# %% [markdown] tags=[]
# # Settings

# %% tags=[]
CORRELATION_METHOD_NAME = "spearman"

# %% tags=[]
GENE_SELECTION_STRATEGY = "var_pc_log2"

# %% tags=[]
# Tissues with largest sample size from GTEx (see nbs/05_preprocessing/00-gtex_v8-split_by_tissue.ipynb)
TISSUES = [
    "Muscle - Skeletal",
    "Whole Blood",
    "Skin - Sun Exposed (Lower leg)",
    "Adipose - Subcutaneous",
    "Artery - Tibial",
]

# %% tags=[]
# range of k values that will be used by the clustering algorithm
K_RANGE = [2] + np.arange(5, 100 + 1, 5).tolist() + [125, 150, 175, 200]

# %% tags=[]
# number of times the algorithm will be run for each configuration; it will pick the "best" partition among these, according
# to some internal criteria (see the algorithm's documentation for more information on this parameter, which is `n_init`).
N_INIT = 50

# %% tags=[]
INITIAL_RANDOM_STATE = 12345


# %% tags=[]
def process_similarity_matrix(similarity_matrix):
    """
    It process the similarity matrix to perform any needed adjustment before performing cluster analysis on it.
    """
    # see comments for pearson
    return similarity_matrix.abs()


# %% tags=[]
def get_distance_matrix(similarity_matrix):
    """
    It converts the processed similarity matrix into a distance matrix. This is needed to compute some clustering quality measures.
    """
    # see comments for pearson
    return 1.0 - similarity_matrix


# %% tags=[]
assert process_similarity_matrix(pd.Series(1.0)).squeeze() == 1
assert process_similarity_matrix(pd.Series(0.0)).squeeze() == 0
assert process_similarity_matrix(pd.Series(-1.0)).squeeze() == 1

# %% tags=[]
assert get_distance_matrix(process_similarity_matrix(pd.Series(1.0))).squeeze() == 0
assert get_distance_matrix(process_similarity_matrix(pd.Series(0.0))).squeeze() == 1
assert get_distance_matrix(process_similarity_matrix(pd.Series(-1.0))).squeeze() == 0

# %% [markdown] tags=[]
# # Paths

# %% tags=[]
INPUT_DIR = conf.GTEX["SIMILARITY_MATRICES_DIR"]
display(INPUT_DIR)
assert INPUT_DIR.exists()

# %% tags=[]
OUTPUT_DIR = conf.GTEX["CLUSTERING_DIR"]
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
display(INPUT_DIR)

# %% [markdown] tags=[]
# # Setup clustering options

# %% tags=[]
CLUSTERING_OPTIONS = {}

CLUSTERING_OPTIONS["K_RANGE"] = K_RANGE
CLUSTERING_OPTIONS["KMEANS_N_INIT"] = N_INIT

display(CLUSTERING_OPTIONS)

# %% [markdown] tags=[]
# # Get data files

# %% tags=[]
# get input data files according to Settings
input_files = list(
    INPUT_DIR.glob(f"*-{GENE_SELECTION_STRATEGY}-{CORRELATION_METHOD_NAME}.pkl")
)
display(len(input_files))
display(input_files[:5])

# %% [markdown] tags=[]
# ## Filter files by selected tissues

# %% tags=[]
# convert tissue name to internal, simplified representation
tissue_names_map = {simplify_string(t.lower()): t for t in TISSUES}
display(tissue_names_map)

# %% tags=[]
# filter by selected tissues
input_files = sorted(
    [
        f
        for f in input_files
        if any(f"gtex_v8_data_{tn}-" in f.name for tn in tissue_names_map)
    ]
)
display(len(input_files))
display(input_files)

# make sure we got the right number
assert len(input_files) == len(TISSUES), len(TISSUES)

# %% [markdown] tags=[]
# ## Show the content of one similarity matrix

# %% tags=[]
sim_matrix = pd.read_pickle(input_files[0])

# %% tags=[]
sim_matrix.shape

# %% tags=[]
sim_matrix.head()

# %% [markdown] tags=[]
# # Clustering

# %% [markdown] tags=[]
# ## Generate clusterers

# %% [markdown] tags=[]
# A "clusterer" is an instance of one clustering algorithm with a specified set of parameters. For instance, KMeans with `n_clusters=2` and `random_state=189`.

# %% tags=[]
clusterers = {}

idx = 0
random_state = INITIAL_RANDOM_STATE

for k in CLUSTERING_OPTIONS["K_RANGE"]:
    clus = SpectralClustering(
        eigen_solver="arpack",
        n_clusters=k,
        n_init=CLUSTERING_OPTIONS["KMEANS_N_INIT"],
        affinity="precomputed",
        random_state=random_state,
    )

    method_name = type(clus).__name__
    clusterers[f"{method_name} #{idx}"] = clus

    random_state = random_state + 1
    idx = idx + 1

# %% tags=[]
display(len(clusterers))

# %% tags=[]
_iter = iter(clusterers.items())
display(next(_iter))
display(next(_iter))

# %% tags=[]
clustering_method_name = method_name
display(clustering_method_name)

# %% [markdown] tags=[]
# ## Generate ensemble

# %% tags=[]
output_files = []
pbar = tqdm(input_files, ncols=100)

for tissue_data_file in pbar:
    pbar.set_description(tissue_data_file.stem)

    # read similarity matrix for this tissue
    sim_matrix = pd.read_pickle(tissue_data_file)
    sim_matrix = process_similarity_matrix(sim_matrix)

    # generate ensemble
    ensemble = generate_ensemble(
        sim_matrix,
        clusterers,
        tqdm_args={"leave": False, "ncols": 100},
    )

    # perform some checks on the generate ensemble
    # there should be a single k among ensemble partitions
    _tmp = ensemble["n_clusters"].value_counts().unique()
    assert _tmp.shape[0] == 1
    assert _tmp[0] == 1

    assert not ensemble["n_clusters"].isna().any()

    assert ensemble.shape[0] == len(clusterers)

    # no partition has negative labels or nan
    assert not np.any(
        [np.isnan(part["partition"]).any() for idx, part in ensemble.iterrows()]
    )
    assert not np.any(
        [(part["partition"] < 0).any() for idx, part in ensemble.iterrows()]
    )

    # all partitions must have the size of the data
    assert np.all(
        [
            part["partition"].shape[0] == sim_matrix.shape[0]
            for idx, part in ensemble.iterrows()
        ]
    )

    # the number of unique labels in the partition must match the k specified
    _real_k_values = ensemble["partition"].apply(lambda x: np.unique(x).shape[0])
    assert np.all(ensemble["n_clusters"].values == _real_k_values.values)

    # add clustering quality measures
    dist_matrix = get_distance_matrix(sim_matrix)

    ensemble = ensemble.assign(
        si_score=ensemble["partition"].apply(
            lambda x: silhouette_score(dist_matrix, x, metric="precomputed")
        ),
    )

    # save
    output_filename = f"{tissue_data_file.stem}-{clustering_method_name}.pkl"
    output_filepath = OUTPUT_DIR / output_filename
    output_files.append(output_filepath)

    ensemble.to_pickle(path=output_filepath)


# %% [markdown] tags=[]
# # Plot cluster quality measures

# %% tags=[]
def get_tissue_name(filename):
    tissue_simplified_name = filename.split("gtex_v8_data_")[1].split(
        f"-{GENE_SELECTION_STRATEGY}"
    )[0]
    return tissue_names_map[tissue_simplified_name]


# %% tags=[]
# combine all partitions across tissues
ensembles = []

for f in output_files:
    tissue_name = get_tissue_name(f.name)

    ensemble = pd.read_pickle(f)[["n_clusters", "si_score"]]
    ensemble["tissue"] = tissue_name

    ensembles.append(ensemble)

ensembles = pd.concat(ensembles, ignore_index=True)

# %% tags=[]
ensembles.head()

# %% tags=[]
with sns.plotting_context("talk", font_scale=0.75), sns.axes_style(
    "whitegrid", {"grid.linestyle": "--"}
):
    fig = plt.figure(figsize=(14, 6))

    ax = sns.pointplot(data=ensembles, x="n_clusters", y="si_score", hue="tissue")

    ax.set_ylabel("Silhouette index\n(higher is better)")
    ax.set_xlabel("Number of clusters ($k$)")
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
    plt.grid(True)
    plt.tight_layout()
    display(fig)
    plt.close(fig)

# %% tags=[]
