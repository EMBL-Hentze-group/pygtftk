#!/usr/bin/env python
"""
 OLOGRAM -- OverLap Of Genomic Regions Analysis using Monte Carlo. Ologram
 annotates peaks (in bed format) using (i) genomic features extracted
 from a GTF file (e.g promoter, tts, gene body, UTR...) (ii) genomic regions tagged with
 particular keys/values in a GTF file (e.g. gene_biotype "protein_coding",
 gene_biotype "LncRNA"...) or (iii) from a BED file (e.g. user-defined regions).

 Each pair {peak file, feature} is randomly shuffled independently across the genome (inter-region
 lengths are considered). Then the probability of intersection under the null
 hypothesis (the peaks and this feature are independent) is deduced thanks to
 this Monte Carlo approach.

 The program will return statistics for both the number of intersections and the
 total lengths (in basepairs) of all intersections.

 Authors : Quentin FERRE <quentin.q.ferre@gmail.com>,
 Guillaume CHARBONNIER <guillaume.charbonnier@outlook.com>,
 and Denis PUTHIER <denis.puthier@univ-amu.fr>.
 """

import argparse
import warnings

warnings.simplefilter(action='ignore', category=FutureWarning)

import multiprocessing
import os
import re
import sys
import time
import copy
import warnings
from functools import partial
import matplotlib.cbook

import numpy as np
import pandas as pd
import pybedtools
from plotnine import (ggplot, aes, position_dodge, ggtitle,
                      geom_bar, ylab, theme, element_blank,
                      element_text, geom_errorbar, theme_bw,
                      geom_label, save_as_pdf_pages, scale_fill_manual,
                      geom_vline, xlab)

from pygtftk import arg_formatter
from pygtftk.bedtool_extension import BedTool
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.stats.intersect.read_bed import \
    read_bed_as_list as read_bed  # Only used here for exclusions
from pygtftk.stats.intersect.overlap_stats_shuffling import \
    compute_overlap_stats  # Main function from the stats.intersect module
from pygtftk.utils import chrom_info_as_dict
from pygtftk.utils import close_properly
from pygtftk.utils import make_outdir_and_file
from pygtftk.utils import make_tmp_file
from pygtftk.utils import message
from pygtftk.utils import sort_2_lists
import gc

__updated__ = "2020-08-01"
__doc__ = """

 OLOGRAM -- OverLap Of Genomic Regions Analysis using Monte Carlo. Ologram
 annotates peaks (in bed format) using (i) genomic features extracted
 from a GTF file (e.g promoter, tts, gene body, UTR...) (ii) genomic regions tagged with
  particular keys/values in a GTF file (e.g. gene_biotype "protein_coding",
  gene_biotype "LncRNA"...) or (iii) from a BED file (e.g. user-defined regions).

 Each pair {peak file, feature} is randomly shuffled independently across the genome (inter-region
 lengths are considered). Then the probability of intersection under the null
 hypothesis (the peaks and this feature are independent) is deduced thanks to
 this Monte Carlo approach. The program will return statistics for both the number of intersections and the
 total lengths (in basepairs) of all intersections.
 
 The null hypothesis is:
 
 H0: The regions of the query (--peak-file) are located independently of the 
 reference (--inputfile or --more-bed) with respect to overlap.
 
 H1: The regions of the query (--peak-file) tend to overlap the 
 reference (--inputfile or --more-bed). 

 OLOGRAM can now also calculate enrichment for n-wise combinations (e.g. [Query + A + B]
 or [Query + B + C]) on sets of regions defined by the user (--more-bed argument).

 Author : Quentin FERRE <quentin.q.ferre@gmail.com>,
 Co-authors : Guillaume CHARBONNIER <guillaume.charbonnier@outlook.com> and
 Denis PUTHIER <denis.puthier@univ-amu.fr>.
 """

__notes__ = """
 -- OLOGRAM is multithreaded and can use many cores, most notably processing one batch
 of shuffles per core. Note that this can be RAM-intensive, on top of the base pygtftk
 processing of a full human GTF can require upwards of 8Gb.
 It is recommended you do not run other programs in the meantime on a laptop.

 -- You may pass custom sets of regions as BED files, especially for multiple overlaps, 
 with the --more-bed arguments to look for enrichment in overlaps for custom annotations.

 -- Genome size is computed from the provided chromInfo file (-c). It should thus only
 contain ordinary chromosomes. -\-chrom-info may also accept 'mm8', 'mm9', 'mm10', 'hg19', 'hg38', 'rn3' or 'rn4'.
 In this case the corresponding size of conventional chromosomes are used. ChrM is not used.

 -- The program produces a pdf file and a tsv file ('_stats_') containing intersection statistics
 for the shuffled BEDs under H0 (peak_file and the considered genomic region are independant):
 number of intersections (N = number of lines in the bed intersect) and total number of overlapping
 base pairs (S).

 The output figure gives, for both statistics, expectation and standard deviation (error bars)
 in the shuffles compared to the actual values.

 It also gives, under the 'fit' label for each statistic, the goodness of fit of the statistic under (H0)
 to a Negative Binomial assessed by a Cramer's V score (fit_quality gives 1-V ; as per Cramer (1948) a good fit
 should have a fit quality above (1 - 0.25 = 0.75) if your nb. of shuffles is in the hundreds, but closer to 0.9
 if it is in the thousands or above.

 The p-value of the true intersection under the distribution characterized by the shuffles is also given, under 'p_value'.
 Finally, the log2 fold change between true and shuffles is also given.

 -- If -\-more-keys is used additional region sets will be tested based on the associated key value.
 As an example, if -\-more-keys is set to the 'gene_biotype' (a key generally found in ensembl GTF), the
 region related to 'protein_coding', 'lncRNA' or any other values for that key will be retrieved merged and tested
 for enrichment.

 -- Use -\-no-basic-feature if you want to perform enrichment analysis on custom, focused annotations only (-\-more-bed or -\-more-key).

 -- The goal of the minibatches is to save RAM. You should increase the number of minibatches, instead of their size.
 You may need to use very small minibatches if you have large sets of regions.

 -- You can exclude regions from the shuffling. This is done by shuffling across a concatenated "sub-genome" obtained by removing
 the excluded regions, but the same ones will be excluded from the peak_file and the GTF/more-bed files.

 -- NB/TODO: Current multithreading needs to be optimized. We recommend using the current version with a single core.
 
 -- BETA : About -\-use-markov. This arguments control whether to use Markov model realisations (of order 2) instead of independant shuffles
 for respectively region lengths and inter-region lengths. This can better capture the structure of the genomic regions repartitions.
 This is not recommended in the general case and can be *very* time-consuming (hours).











PROBABLY MORE OR LESS COPY WHAT IS BELOW AND ADD TO THE DOC
BUT WILL THAT BE DOUBLONS ? FIND A WAY TO PHRASE IT SO I DON'T HAVE TO WRITE EVERYTHING TWICE.
DO REMEMBER THAT THIS IS ALL SHOWN IN THE DOC. Look at the final rst to decide each time.


 -- Support for multiple overlaps is available. Please see the documentation for a more complete description.
 
 If the --more-bed-multiple-overlap argument is used, the query peak file will be compared with the custom
 regions passed to the --more-bed argument, and with them only. For example, you can put as query the binding sites of the Transcription Factor A, in --more-bed the factors B, C and D, and
 see whether A+B+D is an enriched combination.
 




-- Explain exact, explain the three cases depending on target combi size
Exact means that, for example, an orverlap of A+B+C will be counted when looking for A+B+... if exact is False (most cases)
Exact is false by default, it will be true if ...


Furthermore, optionally, you may use dictionary learging to find complexes. Do not ask the algo for more than 20-50 complexes.
This will not change the N S and enrichment result, but will restrict the set of interesting combis for which those are calculated?
    This is done with the multiple-overlap-max-number-of-combinations
        Not needed in most cases ?
        Is very WORK IN PROGRESS
        Explain quickly how it works : making many rebuildings on 
        the matrix of true intervals then selecting the best words with a greedy algorithm

        SAY EXPLICITLY : see documentation for more information. 
        I'M NOT GONNA REWRITE EVERYTHING HERE !
        
    Remember that it is optional
    Do not ask for too many combis





 

 -- For statistical reasons, with multiple sets expected intersections can be low. 
 This can require using more shuffles, but we recommend instead using fewer shuffles
 (dozens) because intersections across many files will use RAM. Instead, shuffle
 across a biologically relevant subsection of the genome (with --bed-incl) instead 
 of the entire genome.

 If you nevertheless want to use many shuffles, look to the ologram_merge_run plugin.

 -- We recommend running the ologram_modl_treeify plugin on the resulting tsv file
 if you use multiple overlaps.

 
 


 Explain that you should use more shuffles OR BETTER, ExCLUSION because 
 you need more power to see all combis, but less shuffles per batch to save RAM
    CAREFUL ABOUT RAM USAGE FOR TONS OF SHUFFLE.

 Explain more dict learning, and say it is only useful if you have lots of sets,
  otherwise do all. And it is biaised for the enriched ones obviously.

 
(between sets, 'within sets' maybe for a future version)


 Talk about the treeify plugin ?



-- Only intersections with the query are counted. ie. Query+A+B is counted, but A+B+C is not, for both shuffles and true and MODL I believe.

-- Here or doc itself ? modl employs ssquishing,  where each line has its original abundance divided  by abundance of most rare (but not lower than abundance_threshold, 1/10000 by default so combis rarer than that will not be found). eg if X = [A * 1000, B * 10], X' = [A * 100, B * 1]

"""


def make_parser():
    """The main argument parser."""
    parser = argparse.ArgumentParser(add_help=True)

    parser_grp = parser.add_argument_group('Arguments')

    # --------------------- Main arguments ----------------------------------- #

    parser_grp.add_argument('-i', '--inputfile',
                            help="Path to the GTF file. Defaults to STDIN",
                            default=sys.stdin,
                            metavar="GTF",
                            type=arg_formatter.FormattedFile(mode='r', file_ext=('gtf', 'gtf.gz')),
                            required=False)

    parser_grp.add_argument('-c', '--chrom-info',
                            help="Tabulated two-columns file. "
                                 "Chromosomes as column 1, sizes as column 2",
                            default=None,
                            metavar="TXT",
                            action=arg_formatter.CheckChromFile,
                            required=False)

    parser_grp.add_argument('-p', '--peak-file',
                            help='The file containing the peaks/regions to be annotated.'
                                 ' (bed format).',
                            default=None,
                            metavar="BED",
                            type=arg_formatter.FormattedFile(mode='r', file_ext='bed'),
                            required=True)

    # --------------------- More regions  ------------------------------------- #

    parser_grp.add_argument('-b', '--more-bed',
                            help="A list of bed files to be considered as additional genomic annotations.",
                            type=arg_formatter.FormattedFile(mode='r', file_ext='bed'),
                            nargs='*',
                            required=False)

    parser_grp.add_argument('-l', '--more-bed-labels',
                            help="A comma separated list of labels (see --more-bed). Optional.",
                            default=None,
                            type=str,
                            required=False)

    parser_grp.add_argument('-e', '--bed-excl',
                            help='Exclusion file. The chromosomes will be shortened by this much for the shuffles of peaks and features.'
                                 ' (bed format).',
                            default=None,
                            metavar="BED",
                            type=arg_formatter.FormattedFile(mode='r', file_ext='bed'),
                            required=False)

    parser_grp.add_argument('-bi', '--bed-incl',
                            help='Opposite of --bed-excl, will perform the same operation but keep only those regions.',
                            default=None,
                            metavar="BED",
                            type=arg_formatter.FormattedFile(mode='r', file_ext='bed'),
                            required=False)

    parser_grp.add_argument('-u', '--upstream',
                            help="Extend the TSS and TTS of in 5' by a given value.",
                            default=1000,
                            type=int,
                            required=False)

    parser_grp.add_argument('-d', '--downstream',
                            help="Extend the TSS and TTS of in  3' by a given value. ",
                            default=1000,
                            type=int,
                            required=False)

    parser_grp.add_argument('-m', '--more-keys',
                            help='A comma separated list of key used for labeling the genome. See Notes.',
                            type=str,
                            default=None,
                            required=False)

    parser_grp.add_argument('-n', '--no-basic-feature',
                            help="No statistics for basic features of GTF. Concentrates on --more-bed and --more-keys.",
                            action="store_true",
                            required=False)






























    # ------------------ Multiple overlaps & dict learning ------------------- #

    parser_grp.add_argument('-mo', '--more-bed-multiple-overlap',
                            help="The more-beds specified will be considered all at once for multiple overlaps.",
                            action='store_true',
                            required=False)



  
    parser_grp.add_argument('-mocs', '--multiple-overlap-target-combi-size',
                            help="Maximum number of sets in the output combinations. Default to -1 meaning no max number. Set it to number of --more-bed +1 to get exact (exclusive) combinations",
                            default=-1,
                            type=int,
                            required=False)


    # Also need -monc, --multiple-overlap-max-number-of-combinations. Default is 2**len(setsB)/2 ?
    parser_grp.add_argument('-monc', '--multiple-overlap-max-number-of-combinations',
                            help="""Maximum number of combinations to consider ... by applying the MODL algorithm dictionary learning pruning to matrix of full overlaps. 
                                Defaults to -1, which means dictionary-learning based pruning is NOT applied and all combinations are returned""",
                            default=-1,
                            type=int,
                            required=False)


 


    # multiple_overlap_custom_combis
    # TODO : Add -moc, --multiple-overlap-custom-combis which is the path to a matrix giv
    # ing which combis to consider. The order will be the same as the more-beds, no ?
    # Decide on the format ! 0 0 1\n 0 1 1, or [[0,1,1],[0,1,1]] !!?? TODO USE THE 
    # FIRST FORMAT AND WRITE SO IN THE DOC !!!!
    # TODO : to find out where to add the arguments, just do a project-wide search for 
    # 'multiple_overlap_max_number_of_combinations' since these will likely be used by 
    # mostly the same functions
    parser_grp.add_argument('-moc', '--multiple-overlap-custom-combis',
                            help="Path to a text ('*.txt') file that will be read as a NumPy matrix, overriding the combinations to be studied. The order is the same as --more-beds.",
                            default=None,
                            type=arg_formatter.FormattedFile(mode='r', file_ext='txt'),
                            required=False)



























    # --------------------- Backend ------------------------------------------ #

    parser_grp.add_argument('-k', '--nb-threads',
                            help='Number of threads for multiprocessing.',
                            type=arg_formatter.ranged_num(0, None),
                            default=1,
                            required=False)

    parser_grp.add_argument('-s', '--seed',
                            help='Numpy random seed.',
                            type=arg_formatter.ranged_num(None, None),
                            default=42,
                            required=False)

    parser_grp.add_argument('-mn', '--minibatch-nb',
                            help='Number of minibatches of shuffles.',
                            type=arg_formatter.ranged_num(0, None),
                            default=10,
                            required=False)

    parser_grp.add_argument('-ms', '--minibatch-size',
                            help='Size of each minibatch, in number of shuffles.',
                            type=arg_formatter.ranged_num(0, None),
                            default=20,
                            required=False)

    parser_grp.add_argument('-ma', '--use-markov',
                            help='Whether to use Markov model realisations (order 2) instead of independant shuffles. See notes.',
                            action='store_true',
                            required=False)

    # --------------------- Output ------------------------------------------- #

    parser_grp.add_argument('-o', '--outputdir',
                            help='Output directory name.',
                            metavar="DIR",
                            default="ologram_output",
                            type=str)

    parser_grp.add_argument('-pw', '--pdf-width',
                            help='Output pdf file width (inches).',
                            type=arg_formatter.ranged_num(0, None),
                            default=None,
                            required=False)

    parser_grp.add_argument('-ph', '--pdf-height',
                            help='Output pdf file height (inches).',
                            type=arg_formatter.ranged_num(0, None),
                            default=None,
                            required=False)

    parser_grp.add_argument('-pf', '--pdf-file-alt',
                            help="Provide an alternative path for the main image. ",
                            default=None,
                            nargs=None,
                            type=arg_formatter.FormattedFile(mode='w', file_ext='pdf'),
                            required=False)

    parser_grp.add_argument('-x', '--no-pdf',
                            help="Do not produce any image file. ",
                            action='store_true',
                            required=False)

    parser_grp.add_argument('-y', '--display-fit-quality',
                            help="Display the negative binomial fit quality on the diagrams. ",
                            action='store_true',
                            required=False)

    parser_grp.add_argument('-tp', '--tsv-file-path',
                            help="Provide an alternative path for text output file.",
                            default=None,
                            type=arg_formatter.FormattedFile(mode='w', file_ext='txt'),
                            required=False)

    parser_grp.add_argument('-j', '--sort-features',
                            help="Whether to sort features in diagrams according to a computed statistic.",
                            choices=[None, "nb_intersections_expectation_shuffled",
                                     "nb_intersections_variance_shuffled",
                                     "nb_intersections_negbinom_fit_quality",
                                     "nb_intersections_log2_fold_change",
                                     "nb_intersections_true",
                                     "nb_intersections_pvalue",
                                     "summed_bp_overlaps_expectation_shuffled",
                                     "summed_bp_overlaps_variance_shuffled",
                                     "summed_bp_overlaps_negbinom_fit_quality",
                                     "summed_bp_overlaps_log2_fold_change",
                                     "summed_bp_overlaps_true",
                                     "summed_bp_overlaps_pvalue"],
                            default=None,
                            type=str,
                            required=False)

    # --------------------- Other input arguments----------------------------- #

    parser_grp.add_argument('-z', '--no-gtf',
                            help="No GTF file is provided as input.",
                            action='store_true',
                            required=False)

    parser_grp.add_argument('-f', '--force-chrom-gtf',
                            help="Discard silently, from GTF, genes outside chromosomes defined in --chrom-info.",
                            action='store_true',
                            required=False)

    parser_grp.add_argument('-w', '--force-chrom-peak',
                            help="Discard silently, from --peak-file, peaks outside chromosomes defined in --chrom-info.",
                            action='store_true',
                            required=False)

    parser_grp.add_argument('-q', '--force-chrom-more-bed',
                            help="Discard silently, from --more-bed files, regions outside chromosomes defined in --chrom-info.",
                            action='store_true',
                            required=False)

    return parser


# -------------------------------------------------------------------------
# The command function
# -------------------------------------------------------------------------


def ologram(inputfile=None,
            outputdir=None,
            peak_file=None,
            chrom_info=None,
            tsv_file_path=None,

            more_bed=None,
            more_bed_labels=None,

            no_gtf=False,
            upstream=1000,
            more_keys=None,
            downstream=1000,
            no_basic_feature=False,
            bed_excl=None,
            bed_incl=None,

            more_bed_multiple_overlap=False,
            multiple_overlap_target_combi_size = None,
            multiple_overlap_max_number_of_combinations = None,
            multiple_overlap_custom_combis = None,

            use_markov=False,
            no_pdf=None,
            pdf_width=5,
            pdf_height=5,
            force_chrom_gtf=False,
            force_chrom_peak=False,
            force_chrom_more_bed=False,
            pdf_file_alt=None,
            nb_threads=1,
            seed=42,
            sort_features=False,
            minibatch_nb=8,
            minibatch_size=25,
            display_fit_quality=False
            ):
    """
    This function is intended to perform statistics on peak intersection. It will compare your peaks to
    classical features (e.g promoter, tts, gene body, UTR,...) and to sets of user provided peaks.
    """

    # -------------------------------------------------------------------------
    # Initial checkups
    # -------------------------------------------------------------------------

    # Set random seed
    np.random.seed(seed)

    # Are we using Markov model realisations instead of shuffling ?
    # If yes, send a warning to the user.
    if use_markov:
        message('Using Markov order 2 shuffling.', type='INFO')
        message(
            'Markov-based null is still in beta at the moment and tends to biais the "null" hypothesis towards association.',
            type='WARNING')

    # Send a warning if nb_threads < available cpu cores
    available_cores = multiprocessing.cpu_count()
    if nb_threads < available_cores:
        message(
            'Using only ' + str(nb_threads) + ' threads, but ' + str(
                available_cores) + ' cores are available. Consider changing the --nb-threads parameter.',
            type='WARNING')


    # -------------------------------------------------------------------------
    # Multiple overlaps on --more-bed parameters check
    # -------------------------------------------------------------------------

    if more_bed_multiple_overlap:
        if more_bed is None :
            message("Multiple overlaps (--more-bed-multiple-overlap) are only computed with the query and user-defined regions : please provide those with the --more-bed argument.",
                    type="ERROR")

    # Useless parameters
    if not more_bed_multiple_overlap:
        if multiple_overlap_target_combi_size != -1:
            message("--multiple-overlap-target-combi-size is ignored when not working with multiple overlaps (--more-bed-multiple-overlap).")
        if multiple_overlap_max_number_of_combinations != -1:
            message("--multiple-overlap-max-number-of-combinations is ignored when not working with multiple overlaps (--more-bed-multiple-overlap).")


    # Enforcing custom combinations
    if multiple_overlap_custom_combis is not None:
        if multiple_overlap_target_combi_size != -1:
            message("--multiple-overlap-target-combi-size is ignored when custom combinations are enforced (with --multiple-overlap-custom-combis).")
        if multiple_overlap_max_number_of_combinations != -1:
            message("--multiple-overlap-max-number-of-combinations is ignored when custom combinations are enforced (with --multiple-overlap-custom-combis)")

        if not more_bed_multiple_overlap:
            message("Cannot use --multiple-overlap-custom-combis without the argument --more-bed-multiple-overlap.",
                    type="ERROR")

    # -------------------------------------------------------------------------
    # If the user wishes, don't provide a GTF to the tool
    # -------------------------------------------------------------------------

    if no_gtf:
        if more_keys is not None:
            message("If --more-keys should be used with a GTF.",
                    type="ERROR")
        if no_basic_feature:
            message("If --no-basic-feature should be used with a GTF.",
                    type="ERROR")
        if more_bed is None:
            message("If --no-gtf is set to True provide --more-bed.",
                    type="ERROR")

    # -------------------------------------------------------------------------
    # If user wants no basic features (e.g prom, genes, exons) then he
    # needs to provide --more-keys or --more-bed
    # -------------------------------------------------------------------------

    if no_basic_feature:
        if more_keys is not None:
            if inputfile is None:
                message("If --more-keys is set you should provide a GTF",
                        type="ERROR")
        else:
            if more_bed is None:
                message("If --no-genomic-feature is set to True "
                        "provide --more-keys or --more-bed.",
                        type="ERROR")
    else:
        if inputfile is None:
            message("Please provide a GTF.",
                    type="ERROR")

        if chrom_info is None:
            message("Please provide a chromInfo file (--chrom-info)",
                    type="ERROR")

    # -------------------------------------------------------------------------
    # chrom_len will store the chromosome sizes.
    # -------------------------------------------------------------------------

    chrom_len = chrom_info_as_dict(chrom_info)

    # -------------------------------------------------------------------------
    # Load the peak file as pybedtools.BedTool object
    # -------------------------------------------------------------------------

    peak_file = pybedtools.BedTool(peak_file.name)

    # -------------------------------------------------------------------------
    # Check chromosomes for peaks are defined in the chrom-info file
    # Depending on force_chrom_peak, peaks undefined in peak_file may
    # be silently removed.
    # -------------------------------------------------------------------------

    peak_chrom_list = set()

    for i in pybedtools.BedTool(peak_file):
        peak_chrom_list.add(i.chrom)

    if not force_chrom_peak:
        for i in peak_chrom_list:
            if i not in chrom_len:
                msg = "Chromosome " + str(i) + " from peak file is undefined in --chrom-info file. "
                message(msg + 'Please fix or use --force-chrom-peak.',
                        type="ERROR")
    else:
        peak_file_sub = make_tmp_file(prefix='peaks_x_chrom_info', suffix='.bed')

        n = 0
        for i in peak_file:
            if i.chrom in chrom_len:
                peak_file_sub.write("\t".join(i.fields) + "\n")
                n += 1

        peak_file_sub.close()

        if n == 0:
            message("The --peak-file file does not contain any genomic feature "
                    "falling in chromosomes declared in --chrom-info.",
                    type="ERROR")

        peak_file = BedTool(peak_file_sub.name)

    # -------------------------------------------------------------------------
    # Sort and merge the peaks
    # -------------------------------------------------------------------------
    # Just in case it was not, sort and merge the file.
    # In any case, it should be short compared to the
    # expected total running time.
    peak_file = peak_file.sort().merge()

    # -------------------------------------------------------------------------
    # Region exclusion
    # -------------------------------------------------------------------------

    # If there is an exclusion of certain regions to be done, do it.
    # Here, we do exclusion on the peak file ('bedA') and the chrom sizes.
    # Exclusion on the other bed files or gtf extracted bed files ('bedsB') is
    # done once we get to them.
    # overlap_stats_shuffling() will handle that, with the same condition : that bed_excl != None

    # If the use supplied an inclusion file instead of an exclusion one, do
    # its "negative" to get back an exclusion file.
    if bed_incl:
        if bed_excl is not None:
            message("Cannot specify both --bed_incl and --bed_excl",
                    type="ERROR")

        # Generate a fake bed for the entire genome, using the chromsizes
        full_genome_bed = [str(chrom) + '\t' + '0' + '\t' + str(chrom_len[chrom]) + '\n' for chrom in chrom_len if
                           chrom != 'all_chrom']
        full_genome_bed = pybedtools.BedTool(full_genome_bed)
        bed_incl = pybedtools.BedTool(bed_incl)
        bed_excl = full_genome_bed.subtract(bed_incl)

    # WARNING : do not modify chrom_info or peak_file afterwards !
    # We can afford to modify chrom_len because we only modify its values, and the
    # rest of the ologram code relies otherwise only on its keys.

    if bed_excl is not None:
        # Treating bed_excl once and for all : turning it into a pybedtools file, merging it and sorting it.
        # NOTE This will prevent later conflicts, if two different pybedtools objects try to access it.
        bed_excl = pybedtools.BedTool(bed_excl)
        bed_excl = bed_excl.sort().merge()
        # Split in its constituent commands in case of very large files

        exclstart = time.time()
        message('Exclusion BED found, proceeding on the BED peaks file. This may take a moment.', type='INFO')

        chrom_len = read_bed.exclude_chromsizes(bed_excl, chrom_len)  # Shorten the chrom_len only once, and separately
        peak_file = read_bed.exclude_concatenate(pybedtools.BedTool(peak_file), bed_excl, nb_threads)

        exclstop = time.time()
        message('Exclusion completed for the BED PEAKS file in ' + str(exclstop - exclstart) + ' s', type='DEBUG')









    # -------------------------------------------------------------------------
    # Read the gtf file and discard any records corresponding to chr not declared
    # in ChromInfo file. This only needs to be done if one want basic feature
    # (default) or more-keys (e.g gene_biotype)
    # -------------------------------------------------------------------------

    if not no_gtf:
        if not no_basic_feature or more_keys:
            gtf = GTF(inputfile, check_ensembl_format=False)
            gtf_chrom_list = gtf.get_chroms(nr=True)

            # -------------------------------------------------------------------------
            # Check chromosomes from the GTF are defined in the chrom-info file
            # -------------------------------------------------------------------------

            if not force_chrom_gtf:
                for i in gtf_chrom_list:
                    if i not in chrom_len:
                        msg = "Chromosome " + str(i) + " from GTF is undefined in --chrom-info file. "
                        message(msg + "Please check your --chrom-info file or use --force-chrom-gtf",
                                type="ERROR")

            # -------------------------------------------------------------------------
            # Subset the GTF using chromosomes defined in chrom-info file.
            # -------------------------------------------------------------------------

            gtf = gtf.select_by_key("seqid", ",".join(chrom_len.keys()))

            if len(gtf) == 0:
                message("The GTF file does not contain any genomic feature "
                        "falling in chromosomes declared in --chrom-info.",
                        type="ERROR")

    # -------------------------------------------------------------------------
    # Check user provided annotations
    # -------------------------------------------------------------------------

    if more_bed is not None:

        if more_bed_labels is not None:

            more_bed_labels = more_bed_labels.split(",")

            for elmt in more_bed_labels:
                if not re.search("^[A-Za-z0-9_]+$", elmt):
                    message("Problem with:" + elmt, type="WARNING")
                    message(
                        "Only alphanumeric characters and '_' allowed for --more-bed-labels",
                        type="ERROR")
            if len(more_bed_labels) != len(more_bed):
                message("--more-bed-labels: the number of labels should be"
                        " the same as the number of bed files "
                        "("
                        "see --more-bed-labels).", type="ERROR")

            if len(more_bed_labels) != len(set(more_bed_labels)):
                message("Redundant labels not allowed.", type="ERROR")
        else:

            message(
                "--more-bed-labels was not set, automatically defaulting to --more-bed file names.",
                type="WARNING")

            # If more_bed is set but not more_bed_labels, will default to using more_bed base names without non-alphanumeric characters

            more_bed_labels = []
            for elmt in more_bed:
                #base_name = pathlib.Path(elmt.name).stem
                cleaned_name = os.path.basename(elmt.name)

                cleaned_name = re.sub("_converted\.[Bb][Ee][Dd][3456]{0,1}$", "", cleaned_name)                
                cleaned_name = re.sub("_pygtftk_?((?!pygtftk).)*$", "", cleaned_name) # In case pygtftk name appears in the initial name...
                cleaned_name = re.sub("[^A-Za-z0-9]+", '_', cleaned_name)

                more_bed_labels += [cleaned_name]

            message("--more-bed-label will be set to: " + ",".join(more_bed_labels), type="DEBUG")




    # -------------------------------------------------------------------------
    # Preparing output files
    # -------------------------------------------------------------------------

    file_out_list = make_outdir_and_file(out_dir=outputdir,
                                         alist=["00_ologram_stats.tsv",
                                                "00_ologram_diagrams.pdf"
                                                ],
                                         force=True)

    data_file, pdf_file = file_out_list

    if no_pdf:
        if pdf_file_alt:
            os.unlink(pdf_file_alt.name)
        os.unlink(pdf_file.name)
        pdf_file = None
    else:
        if pdf_file_alt is not None:

            os.unlink(pdf_file.name)
            pdf_file = pdf_file_alt

            test_path = os.path.abspath(pdf_file.name)
            test_path = os.path.dirname(test_path)

            if not os.path.exists(test_path):
                os.makedirs(test_path)

    if tsv_file_path is not None:

        os.unlink(data_file.name)
        data_file = tsv_file_path

        test_path = os.path.abspath(data_file.name)
        test_path = os.path.dirname(test_path)

        if not os.path.exists(test_path):
            os.makedirs(test_path)

    # -------------------------------------------------------------------------
    # Fill the dict with info about basic features included in GTF
    # -------------------------------------------------------------------------

    # Prepare a partial call with all fixed parameters (ie. everything except
    # the two bed files) for code legibility.
    overlap_partial = partial(compute_overlap_stats, chrom_len=chrom_len,
                              minibatch_size=minibatch_size, minibatch_nb=minibatch_nb,
                              bed_excl=bed_excl, use_markov_shuffling=use_markov,
                              nb_threads=nb_threads)

    # Initialize result dict
    hits = dict()

    if not no_gtf:
        if not no_basic_feature:
            for feat_type in gtf.get_feature_list(nr=True):
                message("Processing " + str(feat_type), type="INFO")
                gtf_sub = gtf.select_by_key("feature", feat_type, 0)
                gtf_sub_bed = gtf_sub.to_bed(name=["transcript_id",
                                                   "gene_id",
                                                   "exon_id"]).sort().merge()  # merging bed file !
                tmp_file = make_tmp_file(prefix="ologram_" + str(feat_type), suffix='.bed')
                gtf_sub_bed.saveas(tmp_file.name)

                del gtf_sub

                hits[feat_type] = overlap_partial(bedA=peak_file, bedsB=gtf_sub_bed, ft_type=feat_type)

            nb_gene_line = len(gtf.select_by_key(key="feature", value="gene"))
            nb_tx_line = len(gtf.select_by_key(key="feature", value="transcript"))

            if nb_gene_line and nb_tx_line:
                # -------------------------------------------------------------------------
                # Get the intergenic regions
                # -------------------------------------------------------------------------
                message("Processing intergenic regions", type="INFO")
                gtf_sub_bed = gtf.get_intergenic(chrom_info,
                                                 0,
                                                 0,
                                                 chrom_len.keys()).merge()

                tmp_bed = make_tmp_file(prefix="ologram_intergenic", suffix=".bed")
                gtf_sub_bed.saveas(tmp_bed.name)

                hits["Intergenic"] = overlap_partial(bedA=peak_file, bedsB=gtf_sub_bed, ft_type="Intergenic")

                # -------------------------------------------------------------------------
                # Get the intronic regions
                # -------------------------------------------------------------------------

                message("Processing : Introns", type="INFO")
                gtf_sub_bed = gtf.get_introns()

                tmp_bed = make_tmp_file(prefix="ologram_introns", suffix=".bed")
                gtf_sub_bed.saveas(tmp_bed.name)

                hits["Introns"] = overlap_partial(bedA=peak_file, bedsB=gtf_sub_bed, ft_type="Introns")

                # -------------------------------------------------------------------------
                # Get the promoter regions
                # -------------------------------------------------------------------------

                message("Processing promoters", type="INFO")
                gtf_sub_bed = gtf.get_tss().slop(s=True,
                                                 l=upstream,
                                                 r=downstream,
                                                 g=chrom_info.name).cut([0, 1, 2,
                                                                         3, 4, 5]).sort().merge()

                tmp_bed = make_tmp_file(prefix="ologram_promoters", suffix=".bed")
                gtf_sub_bed.saveas(tmp_bed.name)

                hits["Promoters"] = overlap_partial(bedA=peak_file, bedsB=gtf_sub_bed, ft_type="Promoters")

                # -------------------------------------------------------------------------
                # Get the tts regions
                # -------------------------------------------------------------------------

                message("Processing terminator", type="INFO")
                gtf_sub_bed = gtf.get_tts().slop(s=True,
                                                 l=upstream,
                                                 r=downstream,
                                                 g=chrom_info.name).cut([0, 1, 2,
                                                                         3, 4, 5]).sort().merge()
                tmp_bed = make_tmp_file(prefix="ologram_terminator", suffix=".bed")
                gtf_sub_bed.saveas(tmp_bed.name)

                hits["Terminator"] = overlap_partial(bedA=peak_file, bedsB=gtf_sub_bed, ft_type="Terminator")

        # -------------------------------------------------------------------------
        # if the user requests --more-keys (e.g. gene_biotype)
        # -------------------------------------------------------------------------

        if more_keys is not None:

            more_keys_list = more_keys.split(",")

            for user_key in more_keys_list:
                user_key_values = set(gtf.extract_data(user_key,
                                                       as_list=True,
                                                       hide_undef=True,
                                                       no_na=True,
                                                       nr=True))

                # Turn the set back into a list, which is predictably
                # sorted, to ensure reproducible results
                user_key_values = sorted(user_key_values)

                for val in user_key_values:

                    gtf_sub = gtf.select_by_key(user_key, val, 0)

                    if len(gtf_sub) > 0:
                        gtf_sub_bed = gtf_sub.to_bed(name=["transcript_id",
                                                           "gene_id",
                                                           "exon_id"]).sort().merge()  # merging bed file !
                        del gtf_sub
                        cur_prefix = "ologram_" + re.sub('\W+', '_',
                                                         user_key) + "_" + re.sub('\W+', '_',
                                                                                  val)
                        tmp_bed = make_tmp_file(prefix=cur_prefix, suffix=".bed")
                        gtf_sub_bed.saveas(tmp_bed.name)

                        ft_type = ":".join([user_key, val])  # Key for the dictionary
                        hits[ft_type] = overlap_partial(bedA=peak_file,
                                                        bedsB=gtf_sub_bed,
                                                        ft_type=ft_type)
                        message("Processing " + str(ft_type), type="INFO")

    # -------------------------------------------------------------------------
    # Process user defined annotations
    # -------------------------------------------------------------------------

    # Stock all of the more_beds if needed for multiple overlaps
    all_more_beds = list()
    all_bed_labels = list()

    if more_bed is not None:
        message("Processing user-defined regions (bed format).")
        for bed_anno, bed_lab in zip(more_bed, more_bed_labels):
            message("Processing " + str(bed_lab), type="INFO")



            if not force_chrom_more_bed:
                chrom_list = set()
                for i in BedTool(bed_anno.name):
                    chrom_list.add(i.chrom)

                for i in chrom_list:
                    if i not in chrom_len:
                        message("Chromosome " + str(
                            i) + " is undefined in --more-bed with label " + bed_lab + ". Maybe use --force-chrom-more-bed.",
                                type="ERROR")
            else:
                bed_anno_sub = make_tmp_file(prefix='more_bed_x_chrom_info' + bed_lab, suffix='.bed')

                n = 0
                for i in BedTool(bed_anno.name):
                    if i.chrom in chrom_len:
                        bed_anno_sub.write("\t".join(i.fields) + "\n")
                        n += 1
                if n == 0:
                    message("The --more-bed file does not contain any genomic features "
                            "falling in chromosomes declared in --chrom-info.",
                            type="ERROR")

                bed_anno_sub.close()
                bed_anno = bed_anno_sub


                # TODO merge all more_bed files, as I merge the peak file


                # TODO Remove all merges from the code, do them only if the argument --merge-regions is true or something.
                # OF COURSE THIS ALSO MEANS ADDING A SANITY CHECK IN THE REBUILDING OF BED FILE, TO SUBSTRACT THE MIN OF ALL
                # TO ENSURE NO NEGATIVE REGIONS.













            import copy

            tmp_bed = make_tmp_file(prefix=bed_lab, suffix=".bed")
            bed_anno_tosave = BedTool(bed_anno.name)
            bed_anno_tosave.saveas(tmp_bed.name)

            # Stock all bed annos if multiple overlap is needed
            # TODO DO IT ONLY IF THE MULTIPLE OVERLAP OPTION IS ACTIVE TO PREVENT USELESS MEMORY CLOGGING
            all_more_beds += [copy.copy(BedTool(bed_anno.name))]
            all_bed_labels += [bed_lab] # Add label to list





            # IDEA : to avoid doublons, maybe only do this particular one if more_bed_multiple_overlap was not requested ?

            # YES ! DO THIS ONLY IF more_bed_multiple_overlap WAS NOT REQUESTED !
            if not more_bed_multiple_overlap:
                message("Processing multiple overlaps for user-defined regions (bed format).")
                hits[bed_lab] = overlap_partial(bedA=peak_file,
                                            bedsB=BedTool(bed_anno.name),
                                            ft_type=bed_lab)

    # TODO : prepare another possibility, where an option such as
    # `-all-more-beds-together` is used,  we do the multiple overlap of the
    # region with ALL of the more beds.
    # yep, that is implemented with more_bed_multiple_overlap !
    # Now, bedsB can be a list !
    if more_bed_multiple_overlap:
        hits['multiple_beds'] = overlap_partial(bedA=peak_file, bedsB=all_more_beds,
        ft_type=all_bed_labels,
            multiple_overlap_target_combi_size = multiple_overlap_target_combi_size,
            multiple_overlap_max_number_of_combinations = multiple_overlap_max_number_of_combinations,
            multiple_overlap_custom_combis = multiple_overlap_custom_combis)





        # WARNING. In other cases, hits[feature_type] is a single dictionary giving
        # stats. In this case, it is a dictionary of dictionaries, one per set
        # combination of interest !
        # So now we must actually unwrap it and add each of its subdictionaries to
        # `hits` as hits[combiN] = hits['multiple_beds'][combiN], then delete the
        # original sprawling `hits['multiple_beds']`
        results_to_add = copy.copy(hits['multiple_beds'])


        # Free memory
        del hits['multiple_beds']
        del all_more_beds

        for combi_human_readable, result in results_to_add.items():
            hits[str(combi_human_readable)] = result



















    # ------------------ Treating the 'hits' dictionary --------------------- #

    if len(hits) == 0:
        message("No feature found.", type="ERROR")

    ### Print the 'hits' dictionary into a tabulated file

    should_print_header = True

    for feature_type in hits.keys():

        current_dict = hits[feature_type]  # This is an ordered dict





        



        # First line should be a header
        if should_print_header:
            header = [str(s) for s in hits[feature_type].keys()]

            data_file.write("\t".join(['feature_type'] + header) + "\n")
            should_print_header = False

        values = []
        for _, v in current_dict.items():
            values = values + [str(v)]

        data_file.write("\t".join([feature_type] + values) + "\n")

    close_properly(data_file)

    # -------------------------------------------------------------------------
    # Read the data
    # -------------------------------------------------------------------------

    d = pd.read_csv(data_file.name, sep="\t", header=0)

    # -------------------------------------------------------------------------
    # Rename the feature type.
    # When --more-keys is used the key and value are separated by ":".
    # This give rise to long name whose display in the plot is ugly.
    # We can break these names using a "\n".
    # -------------------------------------------------------------------------

    d["feature_type"] = [x.replace(":", "\n") for x in d["feature_type"]]

    # -------------------------------------------------------------------------
    # Compute feature order for plotting according to sort_features
    # -------------------------------------------------------------------------

    if sort_features is not None:
        sorted_feat = sort_2_lists(d[sort_features].tolist(),
                                   d.feature_type.tolist())[1]
        feature_order = []
        for x in sorted_feat:
            if x not in feature_order:
                feature_order += [x]


    else:
        feature_order = None


    # -------------------------------------------------------------------------
    # Plot the diagram
    # -------------------------------------------------------------------------

    if pdf_file is not None:
        plot_results(d, data_file, pdf_file, pdf_width, pdf_height, feature_order, more_bed_multiple_overlap, display_fit_quality)
        close_properly(pdf_file)
    close_properly(data_file)


def plot_results(d, data_file, pdf_file, pdf_width, pdf_height, feature_order, should_plot_multiple_combis, display_fit_quality):
    """
    Main plotting function by Q. FERRE and D. PUTHIER.
    """

    if d.shape[0] == 0:
        message("No lines found in input file.",
                type="ERROR")

    # Save the data file
    d.to_csv(open(data_file.name, 'w'), sep="\t", header=True, index=False)

    # -------------------------------------------------------------------------
    # Copy the data
    # -------------------------------------------------------------------------

    dm = d.copy()

    # -------------------------------------------------------------------------
    # Create a new plot
    # -------------------------------------------------------------------------

    message('Adding bar plot.')

    # -------------------------------------------------------------------------
    # Barplot: can be used to plot either 'summed_bp_overlaps'
    # or 'nb_intersections'
    # -------------------------------------------------------------------------

    def plot_this(statname, feature_order=None, display_fit_quality=False):

        # ------------------------- DATA PROCESSING -------------------------- #

        # Collect true and shuffled number of the stat being plotted
        data_ni = dm[['feature_type', statname + '_expectation_shuffled', statname + '_true']]
        maximum = data_ni[[statname + '_expectation_shuffled', statname + '_true']].max(axis=1)

        data_ni.columns = ['Feature', 'Shuffled', 'True']  # Rename columns

        # For later purposes (p-value display), collect the fold change.
        fc = data_ni['True'] / (data_ni['Shuffled'] + 1)

        # Now melt the dataframe
        dmm = data_ni.melt(id_vars='Feature')
        dmm.columns = ['Feature', 'Type', statname]

        # Reorder features if required
        if feature_order is not None:
            dmm.Feature = pd.Categorical(dmm.Feature.tolist(), categories=feature_order, ordered=True)

        # Create plot
        p = ggplot(dmm)
        p += theme_bw()  # Add the black & white theme

        # Bar plot of shuffled vs true
        aes_plot = aes(x='Feature', y=statname, fill='Type')
        p += geom_bar(mapping=aes_plot, stat='identity', alpha=0.6, position='dodge', show_legend=True, width=.6)

        # Add error bars for the standard deviation of the shuffles
        errorbar_mins = dm[statname + '_expectation_shuffled'] - np.sqrt(dm[statname + '_variance_shuffled'])
        errorbar_maxs = dm[statname + '_expectation_shuffled'] + np.sqrt(dm[statname + '_variance_shuffled'])

        # True values have no error
        na_series = pd.Series([np.nan] * len(errorbar_mins))
        errorbar_mins = errorbar_mins.append(na_series)
        errorbar_mins.index = range(len(errorbar_mins))
        errorbar_maxs = errorbar_maxs.append(na_series)
        errorbar_maxs.index = range(len(errorbar_maxs))

        p += geom_errorbar(aes(x='Feature', ymin=errorbar_mins, ymax=errorbar_maxs, fill='Type'), width=.5,
                           position=position_dodge(.6), size=0.3)

        # Text for the p-value
        text = dm[statname + '_pvalue'].append(na_series)
        text.index = range(len(text))

        # Format the text
        def format_pvalue(x):
            if x == 0.0:
                r = 'p<1e-320'  # If the p-value is ~0 (precision limit), say so
            elif x == -1:
                r = 'p=NA'  # If the p-value was -1, we write 'Not applicable'
            else:
                r = 'p=' + '{0:.2g}'.format(x)  # Add 'p=' before and format the p value
            return r

        # Compute the colors for the text box : orange if significantly depleted,
        # green if significantly enriched, black otherwise. For display purposes,
        # p<0.05 counts as significant.
        signif_color = pd.Series(['#b3b3b3'] * len(text))
        for i in range(len(text)):
            if text[i] < 0.05:  # If significant
                if fc[i] < 1: signif_color[i] = '#ffa64d'
                if fc[i] > 1: signif_color[i] = '#6cc67b'

            if text[i] < 1E-10:  # Moreover, if very significant
                if fc[i] < 1: signif_color[i] = '#cc6600'
                if fc[i] > 1: signif_color[i] = '#3c9040'

        text = text.apply(format_pvalue)
        text_pos = (maximum + 0.05 * max(maximum)).append(na_series)
        text_pos.index = range(len(text_pos))

        if display_fit_quality:
            fit_qual_text = dm[statname + '_negbinom_fit_quality'].append(na_series)
            fit_qual_text.index = range(len(fit_qual_text))

            text_with_fit = list()
            for t, f in zip(text.tolist(), fit_qual_text.tolist()):
                text_with_fit += [t + "\n" + 'fit={0:.2g}'.format(f)]
            text = pd.Series(text_with_fit)

        aes_plot = aes(x='Feature', y=text_pos, label=text)
        p += geom_label(mapping=aes_plot, stat='identity',
                        size=5, boxstyle='round', label_size=0.2,
                        color='white', fill=signif_color)












        # TODO : add a red asterisk if the fit is bad, and add this in notes or legend or something



























        # Theme
        p += theme(legend_title=element_blank(),
                   legend_position="top",
                   legend_box_spacing=0.65,
                   legend_key_size=8,
                   legend_text=element_text(size=8),
                   legend_key=element_blank(),
                   axis_title_x=element_blank(),
                   axis_title_y=element_text(colour='#333333',
                                             size=8,
                                             hjust=4,
                                             angle=90,
                                             face="plain"),
                   axis_text_y=element_text(size=5,
                                            margin={'r': 0},
                                            angle=0),
                   axis_text_x=element_text(size=5,
                                            angle=90,
                                            hjust=1)
                   )

        # Add a nicer set of colors.
        p += scale_fill_manual(values={'Shuffled': '#757575', 'True': '#0288d1'})


        # Remember the feature order for potential future use
        order_of_features = dmm.Feature.tolist()

        return p, order_of_features

    # -------------------------------------------------------------------------
    # Volcano plot (combining both N and S results
    # -------------------------------------------------------------------------

    # TODO: add some repelling points asap as available in plotnine.

    def plot_volcano():

        mat_n = d[['feature_type',
                   'nb_intersections_log2_fold_change',
                   'nb_intersections_pvalue']]
        # Uncomputed pvalue are discarded
        mat_n = mat_n.drop(mat_n[mat_n.nb_intersections_pvalue == -1].index)
        # Pval set to 0 are changed to  1e-320
        mat_n.loc[mat_n['nb_intersections_pvalue'] == 0, 'nb_intersections_pvalue'] = 1e-320
        mat_n = mat_n.assign(minus_log10_pvalue=list(-np.log10(list(mat_n.nb_intersections_pvalue))))
        mat_n.columns = ['Feature', 'log2_FC', 'pvalue', 'minus_log10_pvalue']
        mat_n = mat_n.assign(Statistic=['N'] * mat_n.shape[0])

        mat_s = d[['feature_type',
                   'summed_bp_overlaps_log2_fold_change',
                   'summed_bp_overlaps_pvalue']]
        # Uncomputed pvalue are discarded
        mat_s = mat_s.drop(mat_s[mat_s.summed_bp_overlaps_pvalue == -1].index)
        # Pval set to 0 are changed to  1e-320
        mat_s.loc[mat_s['summed_bp_overlaps_pvalue'] == 0, 'summed_bp_overlaps_pvalue'] = 1e-320
        mat_s = mat_s.assign(minus_log10_pvalue=list(-np.log10(list(mat_s.summed_bp_overlaps_pvalue))))
        mat_s.columns = ['Feature', 'log2_FC', 'pvalue', 'minus_log10_pvalue']
        mat_s = mat_s.assign(Statistic=['S'] * mat_s.shape[0])

        df_volc = mat_n.append(mat_s)

        p = ggplot(data=df_volc, mapping=aes(x='log2_FC', y='minus_log10_pvalue'))
        p += geom_vline(xintercept=0, color='darkgray')
        p += geom_label(aes(label='Feature', fill='Statistic'),
                        size=5,
                        color='black',
                        alpha=.5,
                        label_size=0)
        p += ylab('-log10(pvalue)') + xlab('log2(FC)')
        p += ggtitle('Volcano plot (for both N and S statistics)')
        p += scale_fill_manual(values={'N': '#7570b3', 'S': '#e7298a'})
        p += theme_bw()

        return p



    def plot_multi_features(list_of_combis):
        """
        Turn a list of combinations (like ['A+B', 'A+B+C']) into a heatmap
        """
                
        import itertools
        import pandas as pd
        import seaborn as sns

        # Turn list of strings into nested list : remove '[]' and spaces and split combi
        combin = []
        for combi in list_of_combis:
            combi_clean = combi.translate({ord(i): None for i in ['[',']',' ']}).split('+')
            combin += [combi_clean]

        # Get all unique elements
        def get_unique_elements(combin): return sorted(list(set(itertools.chain(*combin))))
        all_elements = get_unique_elements(combin)

        # Turn those lists into logical vector for presence
        df_raw = []
        for combi in combin:
            dict_current = {}
            dict_current['combi'] = '+'.join(combi)

            for e in all_elements:
                current_elem = str(e)
                if e in combi: dict_current[e] = True
                else: dict_current[e] = False

            df_raw.append(dict_current)

        df = pd.DataFrame(df_raw)

        df_melt = pd.melt(df, id_vars = ["combi"]) # Melt for plotting



        # Compute a different fill color for each
        palette = sns.color_palette('deep', len(all_elements))
        def rgb2hex(r,g,b):
            return "#{:02x}{:02x}{:02x}".format(int(255*r), int(255*g), int(255*b))
        elements_palette = {e:rgb2hex(*p) for e,p in zip(all_elements, palette)}
        elements_palette["Null"] = "#ffffff"

        colors_for_plot = []
        for _, vrow in df_melt.iterrows():
            current_color = None

            # Only add the color if the combination contains the element
            if vrow["value"] == False :
                current_color = "Null"
            else:
                current_color = str(vrow["variable"])

            colors_for_plot.append(current_color)

        df_melt["colors_for_plot"] = colors_for_plot




        ### Plot

        from plotnine import ggplot, aes, geom_tile, geom_text, scale_fill_manual, theme, element_rect, element_text

        p = ggplot(df_melt, aes(x = "combi", y = "variable")) + geom_tile(aes(width=.9, height=.9, fill = "colors_for_plot")) + scale_fill_manual(elements_palette, guide = False) + theme(plot_background=element_rect(fill='white')) + theme(axis_text_x=element_text(rotation=90, hjust=1))

        return p
        # For the future : how to share axis

        """
        Not possibel yet in plotnine. So produce this, GIVE IT THE SAME WIDTH AS THE MAIN FIGURE,
        and add a label of text like 'Subplots are not yet supported in plotnine which is the backend we use, but here is a clearler plot. It has mostly the same size as the original one and the COMBIS ARE IN THE SAME ORDER, so you can just
        copy paste it in an image editor to make it more readable'
        """

        """
        Conclusion : simply add this plot to the plot produced by default by OLOGRAM.py if the --more-bed-overlap flag is active. Ensure the combis are given in the SAME ORDER as in the above graph.
        And that's it, really.
        """

    # -------------------------------------------------------------------------
    # call plotting functions
    # -------------------------------------------------------------------------

    # Compute the plots for both statistics
    p1, p1_feature_order = plot_this('summed_bp_overlaps', feature_order, display_fit_quality)
    p1 += ylab("Nb. of overlapping base pairs") + ggtitle('Total overlap length per region type')
    p2, p2_feature_order = plot_this('nb_intersections', feature_order, display_fit_quality) 
    p2 += ylab("Number of intersections") + ggtitle('Total nb. of intersections per region type')
    p3 = plot_volcano()

    # Graphical visualisation of the combinations for multiple overlap cases
    if should_plot_multiple_combis:
        p4 = plot_multi_features(p1_feature_order)

    # -------------------------------------------------------------------------
    # Computing page size
    # -------------------------------------------------------------------------

    nb_ft = len(list(d['feature_type'].unique()))

    if pdf_width is None:
        panel_width = 0.6
        pdf_width = panel_width * nb_ft

        if pdf_width > 100:
            pdf_width = 100
            message("Setting --pdf-width to 100 (limit)")

    if pdf_height is None:
        pdf_height = 5

    message("Page width set to " + str(pdf_width))
    message("Page height set to " + str(pdf_height))
    figsize = (pdf_width, pdf_height)

    # -------------------------------------------------------------------------
    # Turn warning off. Both pandas and plotnine use warnings for deprecated
    # functions. I need to turn they off although I'm not really satisfied with
    # this solution...
    # -------------------------------------------------------------------------

    warnings.filterwarnings("ignore", category=matplotlib.cbook.MatplotlibDeprecationWarning)

    def fxn():
        warnings.warn("deprecated", DeprecationWarning)

    # -------------------------------------------------------------------------
    # Saving
    # -------------------------------------------------------------------------

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fxn()

        message("Saving diagram to file : " + pdf_file.name)
        message("Be patient. This may be long for large datasets.")


        plots = [p1 + theme(figure_size=figsize),
                 p2 + theme(figure_size=figsize),
                 p3 + theme(figure_size=figsize)]

        if should_plot_multiple_combis:
            plots += [p4 + theme(figure_size=figsize)]

        # NOTE : We must manually specify figure size with save_as_pdf_pages
        save_as_pdf_pages(filename=pdf_file.name,
                          plots=plots,
                          width=pdf_width,
                          height=pdf_height)

    gc.disable()


def main():
    """The main function."""

    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    ologram(**args)


if __name__ == '__main__':
    main()


else:

    # 'Bats' tests
    test = '''
        #ologram: get example files
        @test "ologram_0" {
             result=`gtftk get_example -d simple_02 -f '*'`
          [ "$result" = "" ]
        }

        #ologram: run on simple test file
        @test "ologram_1" {
             result=`rm -Rf ologram_output; gtftk ologram -i simple_02.gtf -p simple_02_peaks.bed -c simple_02.chromInfo -u 2 -d 2 -K ologram_output --no-date -k 8`
          [ "$result" = "" ]
        }

        #ologram: proper number of true intersections
        @test "ologram_2" {
         result=`cat ologram_output/00_ologram_stats.tsv | grep gene | cut -f 6`
          [ "$result" = "16" ]
        }

        #ologram: proper number of shuffled intersections
        @test "ologram_3" {
         result=`cat ologram_output/00_ologram_stats.tsv | grep gene | cut -f 2`
          [ "$result" = "14.77" ]
        }

        #ologram: overlapping bp
        @test "ologram_4" {
         result=`cat ologram_output/00_ologram_stats.tsv | grep gene | cut -f 12`
          [ "$result" = "75" ]
        }

        #ologram: shuffled overlapping bp
        @test "ologram_5" {
         result=`cat ologram_output/00_ologram_stats.tsv | grep gene | cut -f 8`
          [ "$result" = "65.98" ]
        }

        #ologram: shuffled overlapping bp variance
        @test "ologram_6" {
         result=`cat ologram_output/00_ologram_stats.tsv | grep gene | cut -f 9`
          [ "$result" = "18.54" ]
        }

        #ologram: shuffled overlapping bp fitting
        @test "ologram_7" {
         result=`cat ologram_output/00_ologram_stats.tsv | grep gene | cut -f 10`
          [ "$result" = "0.70573" ]
        }
        '''







    # TODO Finish adding a BATS test with multiple overlaps and dict learning !!!

    """

    #ologram: get example files
    @test "ologram_8" {
         result=`gtftk get_example -d simple_07 -f '*'`
      [ "$result" = "" ]
    }


    #ologram: multiple overlaps and dict learning
    @test "ologram_9" {
         result=`rm -Rf ologram_output; gtftk ologram -z -p simple_07_peaks.bed -c simple_07.chromInfo -u 2 -d 2 -K ologram_output --no-date -k 8 --more-bed simple_07_peaks.1.bed simple_07_peaks.2.bed --more-bed-multiple-overlap`
      [ "$result" = "" ]
    }

    #ologram: multiple overlaps and dict learning
    @test "ologram_10" {
         result=`rm -Rf ologram_output; gtftk ologram -z -p simple_07_peaks.bed -c simple_07.chromInfo -u 2 -d 2 -K ologram_output --no-date -k 8 --more-bed simple_07_peaks.1.bed simple_07_peaks.2.bed --more-bed-multiple-overlap --multiple-overlap-target-combi-size 3 --multiple-overlap-max-number-of-combinations 4
         --max-combi-whatever 2`
      [ "$result" = "" ]
    }


    # TODO ologram: check which combinations were found and in which abuncance
    # In simple_07 .1. is a subset of raw and .2. is a subset of 1, so the combis should be [1,1,0] and [1,1,1]
    """




    cmd = CmdObject(name="ologram",
                    message="Statistics on bed file intersections with genomic features.",
                    parser=make_parser(),
                    fun=os.path.abspath(__file__),
                    desc=__doc__,
                    group="ologram",
                    notes=__notes__,
                    updated=__updated__,
                    test=test)
