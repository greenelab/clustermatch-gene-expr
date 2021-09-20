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

from clustermatch import conf
from clustermatch.clustering import generate_ensemble

# %% [markdown] tags=[]
# # Settings

# %% tags=[]
CORRELATION_METHOD_NAME = "clustermatch_k2to5"

# %% tags=[]
# we don't have gene subsets for recount2
# GENE_SELECTION_STRATEGY = "var_pc_log2"

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
    # for clustermatch, negative values are meaningless, so we replace them by zero
    similarity_matrix[similarity_matrix < 0.0] = 0.0
    return similarity_matrix


# %% tags=[]
def get_distance_matrix(similarity_matrix):
    """
    It converts the processed similarity matrix into a distance matrix. This is needed to compute some clustering quality measures.
    """
    # the clustermatch coefficient goes from 0 (sometime also negative values that are mean the same as zero) to 1.0
    # the distance is jst 1 minor the coefficient
    return 1.0 - similarity_matrix


# %% [markdown] tags=[]
# # Paths

# %% tags=[]
INPUT_DIR = conf.RECOUNT2["SIMILARITY_MATRICES_DIR"]
display(INPUT_DIR)
assert INPUT_DIR.exists()

# %% tags=[]
OUTPUT_DIR = conf.RECOUNT2["CLUSTERING_DIR"]
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
input_files = list(INPUT_DIR.glob(f"*-{CORRELATION_METHOD_NAME}.pkl"))
display(len(input_files))
display(input_files)

assert len(input_files) == 1

# %% tags=[]
data_file = input_files[0]

# %% [markdown] tags=[]
# ## Show the content of one similarity matrix

# %% tags=[]
sim_matrix = pd.read_pickle(data_file)

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
# read similarity matrix for this tissue
sim_matrix = pd.read_pickle(data_file)
sim_matrix = process_similarity_matrix(sim_matrix)

# %% tags=[]
# generate ensemble
ensemble = generate_ensemble(
    sim_matrix,
    clusterers,
    tqdm_args={"leave": False, "ncols": 100},
)

# %% tags=[]
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
assert not np.any([(part["partition"] < 0).any() for idx, part in ensemble.iterrows()])

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

# %% tags=[]
# add clustering quality measures
dist_matrix = get_distance_matrix(sim_matrix)

ensemble = ensemble.assign(
    si_score=ensemble["partition"].apply(
        lambda x: silhouette_score(dist_matrix, x, metric="precomputed")
    ),
)

# save
output_filename = f"{data_file.stem}-{clustering_method_name}.pkl"
output_filepath = OUTPUT_DIR / output_filename

ensemble.to_pickle(path=output_filepath)

# %% [markdown] tags=[]
# # Plot cluster quality measures

# %% tags=[]
ensemble.shape

# %% tags=[]
ensemble.head()

# %% tags=[]
with sns.plotting_context("talk", font_scale=0.75), sns.axes_style(
    "whitegrid", {"grid.linestyle": "--"}
):
    fig = plt.figure(figsize=(14, 6))

    ax = sns.pointplot(data=ensemble, x="n_clusters", y="si_score")

    ax.set_ylabel("Silhouette index\n(higher is better)")
    ax.set_xlabel("Number of clusters ($k$)")
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
    plt.grid(True)
    plt.tight_layout()
    display(fig)
    plt.close(fig)

# %% tags=[]
