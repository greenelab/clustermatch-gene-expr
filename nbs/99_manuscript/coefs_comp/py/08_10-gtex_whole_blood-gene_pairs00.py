# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: all,-execution,-papermill,-trusted
#     notebook_metadata_filter: -jupytext.text_representation.jupytext_version
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown] tags=[]
# # Description

# %% [markdown] tags=[]
# It selects a set of specific gene pairs from a tissue, and checks if the relationship is replicated on other tissues.
# It also uses GTEx metadata (such as sex) to explain relationships.

# %% [markdown] tags=[]
# # Modules

# %% tags=[]
import pandas as pd

from scipy.stats import pearsonr, spearmanr
import matplotlib.pyplot as plt
import seaborn as sns

from ccc import conf
from ccc.coef import ccc

# %% [markdown] tags=[]
# # Settings

# %% tags=[]
# this gene pair was originally found with ccc on whole blood
# interesting: https://clincancerres.aacrjournals.org/content/26/21/5567.figures-only
gene0_id, gene1_id = "ENSG00000147050.14", "ENSG00000183878.15"
gene0_symbol, gene1_symbol = "KDM6A", "UTY"

# %% [markdown] tags=[]
# # Paths

# %% tags=[]
TISSUE_DIR = conf.GTEX["DATA_DIR"] / "data_by_tissue"
assert TISSUE_DIR.exists()

# %% tags=[]
OUTPUT_FIGURE_DIR = (
    conf.MANUSCRIPT["FIGURES_DIR"]
    / "coefs_comp"
    / f"{gene0_symbol.lower()}_vs_{gene1_symbol.lower()}"
)
OUTPUT_FIGURE_DIR.mkdir(parents=True, exist_ok=True)
display(OUTPUT_FIGURE_DIR)

# %% [markdown] tags=[]
# # Data

# %% [markdown] tags=[]
# ## GTEx metadata

# %% tags=[]
gtex_metadata = pd.read_pickle(conf.GTEX["DATA_DIR"] / "gtex_v8-sample_metadata.pkl")

# %% tags=[]
gtex_metadata.shape

# %% tags=[]
gtex_metadata.head()

# %% [markdown] tags=[]
# ## Gene Ensembl ID -> Symbol mapping

# %% tags=[]
gene_map = pd.read_pickle(conf.GTEX["DATA_DIR"] / "gtex_gene_id_symbol_mappings.pkl")

# %% tags=[]
gene_map = gene_map.set_index("gene_ens_id")["gene_symbol"].to_dict()

# %% tags=[]
assert gene_map["ENSG00000145309.5"] == "CABS1"

# %% tags=[]
assert gene_map[gene0_id] == gene0_symbol
assert gene_map[gene1_id] == gene1_symbol

# %% [markdown] tags=[]
# # Compute correlation on all tissues

# %% tags=[]
res_all = pd.DataFrame(
    {
        f.stem.split("_data_")[1]: {
            "cm": ccc(data[gene0_id], data[gene1_id]),
            "pearson": pearsonr(data[gene0_id], data[gene1_id])[0],
            "spearman": spearmanr(data[gene0_id], data[gene1_id])[0],
        }
        for f in TISSUE_DIR.glob("*.pkl")
        if (data := pd.read_pickle(f).T[[gene0_id, gene1_id]].dropna()) is not None
        and data.shape[0] > 10
    }
).T.abs()

# %% tags=[]
res_all.shape

# %% tags=[]
res_all.head()

# %% tags=[]
res_all.sort_values("cm")

# %% tags=[]
res_all.sort_values("pearson")

# %% tags=[]
res_all.sort_values("spearman")


# %% [markdown] tags=[]
# # Plot

# %% tags=[]
def get_tissue_file(name):
    """
    Given a part of a tissue name, it returns a file path to the
    expression data for that tissue in GTEx. It fails if more than
    one files are found.

    Args:
        name: a string with the tissue name (or a part of it).

    Returns:
        A Path object pointing to the gene expression file for the
        given tissue.
    """
    tissue_files = []
    for f in TISSUE_DIR.glob("*.pkl"):
        if name in f.name:
            tissue_files.append(f)

    assert len(tissue_files) == 1
    return tissue_files[0]


# %% tags=[]
# testing
_tmp = get_tissue_file("whole_blood")
assert _tmp.exists()


# %% tags=[]
def simplify_tissue_name(tissue_name):
    return f"{tissue_name[0].upper()}{tissue_name[1:].replace('_', ' ')}"


# %% tags=[]
assert simplify_tissue_name("whole_blood") == "Whole blood"
assert simplify_tissue_name("uterus") == "Uterus"


# %% tags=[]
def plot_gene_pair(
    tissue_name, gene0, gene1, hue=None, kind="hex", ylim=None, bins="log"
):
    """
    It plots (joint plot) a gene pair from the given tissue. It saves the plot
    for the manuscript.
    """
    # merge gene expression with metadata
    tissue_file = get_tissue_file(tissue_name)
    tissue_data = pd.read_pickle(tissue_file).T[[gene0, gene1]]
    tissue_data = pd.merge(
        tissue_data,
        gtex_metadata,
        how="inner",
        left_index=True,
        right_index=True,
        validate="one_to_one",
    )

    # get gene symbols
    gene0_symbol, gene1_symbol = gene_map[gene0], gene_map[gene1]
    display((gene0_symbol, gene1_symbol))

    # compute correlations for this gene pair
    _clustermatch = ccc(tissue_data[gene0], tissue_data[gene1])
    _pearson = pearsonr(tissue_data[gene0], tissue_data[gene1])[0]
    _spearman = spearmanr(tissue_data[gene0], tissue_data[gene1])[0]

    _title = f"{simplify_tissue_name(tissue_name)}\n$c={_clustermatch:.2f}$  $p={_pearson:.2f}$  $s={_spearman:.2f}$"

    other_args = {
        "kind": kind,  # if hue is None else "scatter",
        "rasterized": True,
    }
    if hue is None:
        other_args["bins"] = bins
    else:
        other_args["hue_order"] = ["Male", "Female"]

    with sns.plotting_context("paper", font_scale=1.5):
        p = sns.jointplot(
            data=tissue_data,
            x=gene0,
            y=gene1,
            hue=hue,
            **other_args,
            # ylim=(0, 500),
        )

        if ylim is not None:
            p.ax_joint.set_ylim(ylim)

        gene_x_id = p.ax_joint.get_xlabel()
        gene_x_symbol = gene_map[gene_x_id]
        p.ax_joint.set_xlabel(f"{gene_x_symbol}", fontstyle="italic")

        gene_y_id = p.ax_joint.get_ylabel()
        gene_y_symbol = gene_map[gene_y_id]
        p.ax_joint.set_ylabel(f"{gene_y_symbol}", fontstyle="italic")

        p.fig.suptitle(_title)

        # save
        output_file = (
            OUTPUT_FIGURE_DIR
            / f"gtex_{tissue_name}-{gene_x_symbol}_vs_{gene_y_symbol}.svg"
        )
        display(output_file)

        plt.savefig(
            output_file,
            bbox_inches="tight",
            dpi=300,
            facecolor="white",
        )

    return tissue_data


# %% [markdown] tags=[]
# ## In whole blood (where this gene pair was found)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "whole_blood",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% [markdown] tags=[]
# ## Lowest tissues in ccc

# %% tags=[]
_tissue_data = plot_gene_pair(
    "uterus",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "ovary",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "vagina",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "brain_cerebellum",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "small_intestine_terminal_ileum",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "brain_spinal_cord_cervical_c1",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "testis",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% [markdown] tags=[]
# ## Highest tissues in ccc

# %% tags=[]
_tissue_data = plot_gene_pair(
    "cells_cultured_fibroblasts",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "breast_mammary_tissue",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% [markdown] tags=[]
# ## Pearson low, CCC high

# %% tags=[]
_tissue_data = plot_gene_pair(
    "brain_anterior_cingulate_cortex_ba24",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "brain_amygdala",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "brain_frontal_cortex_ba9",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "bladder",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "heart_atrial_appendage",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% [markdown] tags=[]
# ## Spearman low, CCC high

# %% tags=[]
_tissue_data = plot_gene_pair(
    "heart_left_ventricle",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "adipose_visceral_omentum",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "skin_not_sun_exposed_suprapubic",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% tags=[]
_tissue_data = plot_gene_pair(
    "pancreas",
    gene0_id,
    gene1_id,
    hue="SEX",
    kind="scatter",
)

# %% [markdown] tags=[]
# # Create final figure

# %% tags=[]
from svgutils.compose import Figure, SVG, Panel

# %% tags=[]
Figure(
    "607.67480cm",
    "870.45984cm",
    Panel(
        SVG(OUTPUT_FIGURE_DIR / "gtex_whole_blood-KDM6A_vs_UTY.svg").scale(0.5),
        SVG(OUTPUT_FIGURE_DIR / "gtex_testis-KDM6A_vs_UTY.svg").scale(0.5).move(200, 0),
        SVG(OUTPUT_FIGURE_DIR / "gtex_cells_cultured_fibroblasts-KDM6A_vs_UTY.svg")
        .scale(0.5)
        .move(200 * 2, 0),
    ),
    Panel(
        SVG(OUTPUT_FIGURE_DIR / "gtex_brain_cerebellum-KDM6A_vs_UTY.svg").scale(0.5),
        SVG(OUTPUT_FIGURE_DIR / "gtex_small_intestine_terminal_ileum-KDM6A_vs_UTY.svg")
        .scale(0.5)
        .move(200, 0),
        SVG(OUTPUT_FIGURE_DIR / "gtex_breast_mammary_tissue-KDM6A_vs_UTY.svg")
        .scale(0.5)
        .move(200 * 2, 0),
    ).move(0, 220),
    Panel(
        SVG(
            OUTPUT_FIGURE_DIR
            / "gtex_brain_anterior_cingulate_cortex_ba24-KDM6A_vs_UTY.svg"
        ).scale(0.5),
        SVG(OUTPUT_FIGURE_DIR / "gtex_brain_amygdala-KDM6A_vs_UTY.svg")
        .scale(0.5)
        .move(200, 0),
        SVG(OUTPUT_FIGURE_DIR / "gtex_heart_atrial_appendage-KDM6A_vs_UTY.svg")
        .scale(0.5)
        .move(200 * 2, 0),
    ).move(0, 220 * 2),
    Panel(
        SVG(OUTPUT_FIGURE_DIR / "gtex_vagina-KDM6A_vs_UTY.svg").scale(0.5),
        SVG(OUTPUT_FIGURE_DIR / "gtex_ovary-KDM6A_vs_UTY.svg").scale(0.5).move(200, 0),
        SVG(OUTPUT_FIGURE_DIR / "gtex_uterus-KDM6A_vs_UTY.svg")
        .scale(0.5)
        .move(200 * 2, 0),
    ).move(0, 220 * 3),
).save(OUTPUT_FIGURE_DIR / "gtex-KDM6A_vs_UTY-main.svg")

# %% [markdown] tags=[]
# Now open the file, reside to fit drawing to page, and add a white rectangle to the background.

# %% tags=[]
