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
# TODO

# %% [markdown] tags=[]
# # Modules

# %%
# # %load_ext rpy2.ipython

# %% tags=[]
import json
import tempfile
from pathlib import Path

import requests
import pandas as pd
from pandas.api.types import CategoricalDtype
from tqdm import tqdm

from clustermatch import conf

# %% [markdown] tags=[]
# # Settings

# %% tags=[]
DATASET_CONFIG = conf.GTEX
# GTEX_TISSUE = "whole_blood"
# GENE_SEL_STRATEGY = "var_pc_log2"

# %% tags=[]
N_TOP_GENE_PAIRS = 100

# %%
# CLUSTERMATCH_LABEL = "Clustermatch"
# PEARSON_LABEL = "Pearson"
# SPEARMAN_LABEL = "Spearman"

# %% [markdown] tags=[]
# # Paths

# %% tags=[]
INPUT_DIR = DATASET_CONFIG["GENE_PAIR_INTERSECTIONS"]
display(INPUT_DIR)

assert INPUT_DIR.exists()

# %% tags=[]
OUTPUT_DIR = conf.GIANT["RESULTS_DIR"] / "intersection_genes"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
display(OUTPUT_DIR)

# %% [markdown] tags=[]
# # Load gene maps

# %% [markdown]
# These gene mappings include only query genes (gene pairs).

# %%
gene_id_mappings = pd.read_pickle(OUTPUT_DIR / "gene_map-symbol_to_entrezid.pkl")

# %%
gene_id_mappings.shape

# %%
gene_id_mappings.head()

# %%
gene_symbol_to_entrezid = gene_id_mappings.set_index("SYMBOL").squeeze().to_dict()

# %%
gene_entrezid_to_symbol = gene_id_mappings.set_index("ENTREZID").squeeze().to_dict()

# %% [markdown]
# # Functions

# %%
URL_GENE_INFO = "https://hb.flatironinstitute.org/api/genes/"

# %%
URL_TISSUE_PREDICTION = "https://hb.flatironinstitute.org/api/integrations/relevant/"


# %%
def gene_exists(gene_entrez_id):
    url = URL_GENE_INFO + str(gene_entrez_id)
    r = requests.get(url)

    if r.status_code != 200:
        return False

    data = r.json()
    return "entrez" in data and "standard_name" in data


# %%
# testing
assert gene_exists(3458)
assert not gene_exists(100129354)


# %%
def predict_tissue(gene_pair_tuple):
    for gene in gene_pair_tuple:
        if not gene_exists(gene):
            return None

    params = {"entrez": list(gene_pair_tuple)}
    r = requests.post(URL_TISSUE_PREDICTION, json=params)
    data = r.json()

    # check if top tissue is brenda
    top_id = 0
    while data[top_id]["context"]["term"]["database"]["name"] != "BRENDA Ontology":
        top_id += 1

    return data[top_id]["slug"], data[top_id]["url"]


# %%
# testing
assert predict_tissue(("6903", "3458")) == (
    "nervous-system",
    "http://hb.flatironinstitute.org/api/integrations/nervous-system/",
)
assert predict_tissue(("100129354", "871")) is None

# cases where the top tissue is not brenda
assert predict_tissue(("3458", "10993")) == (
    "natural-killer-cell",
    "http://hb.flatironinstitute.org/api/integrations/natural-killer-cell/",
)
# FIXME: more tests needed here!

# %%
def rank_genes(all_genes, edges, query_gene_symbols):
    genes_query_degrees = {}
    genes_degrees = {}

    for g in all_genes:
        # connections to query genes
        g_query_genes = edges[
            ((edges["gene1"] == g) & (edges["gene2"].isin(query_gene_symbols)))
            | ((edges["gene2"] == g) & (edges["gene1"].isin(query_gene_symbols)))
        ]

        g_query_degree = g_query_genes["weight"].sum() / g_query_genes.shape[0]

        # connections to all genes
        g_all_genes = edges[(edges["gene1"] == g) | (edges["gene2"] == g)]

        g_degree = g_all_genes["weight"].sum() / g_all_genes.shape[0]

        # save
        genes_query_degrees[g] = g_query_degree
        genes_degrees[g] = g_degree

    # no degree correction
    gene_ranks = [
        (gene, idx)
        for idx, (gene, weight) in enumerate(
            sorted(genes_query_degrees.items(), key=lambda item: -item[1])
        )
    ]

    return (
        pd.DataFrame(gene_ranks)
        .set_index(0)
        .squeeze()
        .rename("rank")
        .rename_axis("gene")
    )


# %%
def get_network(gene_entrezids=None, gene_symbols=None, max_genes=15):
    if gene_entrezids is None and gene_symbols is None:
        raise ValueError("No arguments provided")

    if gene_entrezids is not None:
        if (
            gene_entrezids[0] not in gene_entrezid_to_symbol
            or gene_entrezids[1] not in gene_entrezid_to_symbol
        ):
            return None
        gene_symbols = (
            gene_entrezid_to_symbol[gene_entrezids[0]],
            gene_entrezid_to_symbol[gene_entrezids[1]],
        )
    else:
        if gene_symbols[0] not in gene_symbol_to_entrezid or gene_symbols[1] not in gene_symbol_to_entrezid:
            return None
        gene_entrezids = gene_symbol_to_entrezid[gene_symbols[0]], gene_symbol_to_entrezid[gene_symbols[1]]

    tissue_prediction = predict_tissue(gene_entrezids)
    if tissue_prediction is None:
        return None

    # print(tissue_prediction[0])

    url = tissue_prediction[1] + "network/"
    params = [("entrez", gene_entrezids[0]), ("entrez", gene_entrezids[1])]
    r = requests.get(url, params)
    data = r.json()

    mincut = data["mincut"]
    # print(mincut)

    temp_dir = Path(tempfile.mkdtemp(prefix="giant-"))
    genes_json_file = temp_dir / "genes.json"
    edges_json_file = temp_dir / "edges.json"
    with open(genes_json_file, "w") as gf, open(edges_json_file, "w") as ef:
        json.dump(data["genes"], gf)
        json.dump(data["edges"], ef)

    genes = pd.read_json(genes_json_file)["standard_name"]
    edges = pd.read_json(edges_json_file)[["source", "target", "weight"]]

    df = edges.join(genes.rename("gene1"), on="source", how="left").join(
        genes.rename("gene2"), on="target", how="left"
    )[["gene1", "gene2", "weight"]]

    # df = df[df["weight"] > mincut]

    # prioritize genes
    all_genes = set(df["gene1"]).union(set(df["gene2"]))
    if gene_symbols[0] not in all_genes or gene_symbols[1] not in all_genes:
        return None
    
    all_genes.remove(gene_symbols[0])
    all_genes.remove(gene_symbols[1])

    genes_ranks = rank_genes(all_genes, df, gene_symbols)
    top_genes = set(genes_ranks.head(max_genes).index)
    top_genes.update(gene_symbols)
    df = df[(df["gene1"].isin(top_genes)) & (df["gene2"].isin(top_genes))]

    return (
        df[df["weight"] > mincut].reset_index(drop=True),
        tissue_prediction[0],
        mincut,
    )


# %%
# testing
assert get_network(("IFNG", "SDS")) is None
assert get_network(gene_symbols=("IFNG", "nonExistingGene")) is None
# in this case, UPK3B is not included in the network
assert get_network(gene_symbols=("NR4A3", "UPK3B")) is None

# %%
gene_symbols = ("IFNG", "GLIPR1")
df, df_tissue, _ = get_network(gene_symbols=gene_symbols)
df = df.round(4)
assert df.shape[0] == 134

assert df_tissue == "blood"

pd.testing.assert_series_equal(
    df.iloc[0],
    pd.Series(["HLA-DPA1", "GBP2", 0.8386]),
    check_names=False,
    check_index=False,
)

pd.testing.assert_series_equal(
    df.iloc[54],
    pd.Series(["LCP2", "CASP1", 0.7856]),
    check_names=False,
    check_index=False,
)

pd.testing.assert_series_equal(
    df.iloc[-1],
    pd.Series(["ITGB2", "HLA-DQB1", 0.8782]),
    check_names=False,
    check_index=False,
)

# %%
gene_symbols = ("ZDHHC12", "CCL18")
df, df_tissue, _ = get_network(gene_symbols=gene_symbols)
df = df.round(4)
assert df.shape[0] == 129

assert df_tissue == "macrophage"

pd.testing.assert_series_equal(
    df.iloc[0],
    pd.Series(["CCL3", "SCAMP2", 0.1110]),
    check_names=False,
    check_index=False,
)

pd.testing.assert_series_equal(
    df.iloc[72],
    pd.Series(["ZDHHC12", "CTSB", 0.1667]),
    check_names=False,
    check_index=False,
)

pd.testing.assert_series_equal(
    df.iloc[-1],
    pd.Series(["C1QA", "HLA-DQB1", 0.4485]),
    check_names=False,
    check_index=False,
)


# %%
def convert_gene_pairs(gene_pairs, convert_to_entrezid=False):
    gene_pairs = gene_pairs.reset_index()
    
    if convert_to_entrezid:
        gene_pairs = (
            gene_pairs
            .replace(
                {
                    "level_0": gene_symbol_to_entrezid,
                    "level_1": gene_symbol_to_entrezid,
                }
            )
        )
    
    gene_pairs = (
        gene_pairs[["level_0", "level_1"]]
        .itertuples(index=False, name=None)
    )

    return list(gene_pairs)


# %%
def process_tissue_networks(gene_pairs):
    with tqdm(
        total=min(N_TOP_GENE_PAIRS, len(gene_pairs)),
        ncols=100
    ) as pbar:
        gp_idx = 0
        
        while pbar.n < N_TOP_GENE_PAIRS and gp_idx < len(gene_pairs):
            gp = gene_pairs[gp_idx]
            
            pbar.set_description(",".join(gp))
            
            # check whether file already exists
            output_filepath = output_dir / f"{gp_idx:03d}-{gp[0].lower()}_{gp[1].lower()}.h5"
            if output_filepath.exists():
                gp_idx += 1
                pbar.update(1)
                continue

            _res = get_network(gene_symbols=gp)
            if _res is None:
                gp_idx += 1
                continue

            df, tissue, mincut = _res

            assert not df.isna().any().any()

            with pd.HDFStore(output_filepath, mode="w", complevel=4) as store:
                store.put("data", df, format="table")

                metadata = pd.DataFrame({
                    "tissue": tissue,
                    "mincut": mincut,
                }, index=[0])
                store.put("metadata", metadata, format="table")
            
            gp_idx += 1
            pbar.update(1)


# %% [markdown]
# # Predict tissue for each gene pair

# %% [markdown]
# ## Clustermatch vs Pearson

# %%
output_dir = OUTPUT_DIR / "clustermatch_vs_pearson"
output_dir.mkdir(exist_ok=True, parents=True)

# %%
data = pd.read_pickle(INPUT_DIR / "clustermatch_vs_pearson.pkl").sort_values(
    "clustermatch", ascending=False
)

# %%
data.shape

# %%
data.head()

# %%
gene_pairs = convert_gene_pairs(data)
display(len(gene_pairs))

# %%
gene_pairs[:10]

# %%
process_tissue_networks(gene_pairs)

# %% [markdown]
# ## Clustermatch vs Pearson/Spearman

# %%
output_dir = OUTPUT_DIR / "clustermatch_vs_pearson_spearman"
output_dir.mkdir(exist_ok=True, parents=True)

# %%
data = pd.read_pickle(INPUT_DIR / "clustermatch_vs_pearson_spearman.pkl").sort_values(
    "clustermatch", ascending=False
)

# %%
data.shape

# %%
data.head()

# %%
gene_pairs = convert_gene_pairs(data)
display(len(gene_pairs))

# %%
gene_pairs[:10]

# %%
process_tissue_networks(gene_pairs)

# %% [markdown]
# ## Clustermatch vs Spearman

# %%
output_dir = OUTPUT_DIR / "clustermatch_vs_spearman"
output_dir.mkdir(exist_ok=True, parents=True)

# %%
data = pd.read_pickle(INPUT_DIR / "clustermatch_vs_spearman.pkl").sort_values(
    "clustermatch", ascending=False
)

# %%
data.shape

# %%
data.head()

# %%
gene_pairs = convert_gene_pairs(data)
display(len(gene_pairs))

# %%
gene_pairs[:10]

# %%
process_tissue_networks(gene_pairs)

# %% [markdown]
# ## Pearson vs Clustermatch

# %%
output_dir = OUTPUT_DIR / "pearson_vs_clustermatch"
output_dir.mkdir(exist_ok=True, parents=True)

# %%
data = pd.read_pickle(INPUT_DIR / "pearson_vs_clustermatch.pkl").sort_values(
    "pearson", ascending=False
)

# %%
data.shape

# %%
data.head()

# %%
gene_pairs = convert_gene_pairs(data)
display(len(gene_pairs))

# %%
gene_pairs[:10]

# %%
process_tissue_networks(gene_pairs)

# %% [markdown]
# ## Pearson vs Clustermatch/Spearman

# %%
output_dir = OUTPUT_DIR / "pearson_vs_clustermatch_spearman"
output_dir.mkdir(exist_ok=True, parents=True)

# %%
data = pd.read_pickle(INPUT_DIR / "pearson_vs_clustermatch_spearman.pkl").sort_values(
    "pearson", ascending=False
)

# %%
data.shape

# %%
data.head()

# %%
gene_pairs = convert_gene_pairs(data)
display(len(gene_pairs))

# %%
gene_pairs[:10]

# %%
process_tissue_networks(gene_pairs)

# %%
