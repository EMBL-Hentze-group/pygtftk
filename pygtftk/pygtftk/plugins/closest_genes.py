#!/usr/bin/env python
from __future__ import division
from __future__ import print_function

import argparse
import sys
from _collections import defaultdict

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.utils import close_properly
from pygtftk.utils import message

__updated__ = "2018-02-11"
__doc__ = """
 Find the n closest genes for each genes.
"""
__notes__ = """
 -- The reference region for each gene can be the TSS (the most 5'), the TTS (The most 3') or the whole gene.
 -- The reference region for each closest gene can be the TSS, the whole gene or the TTS.
 -- The closest genes can be searched in a stranded or unstranded fashion.

"""


def make_parser():
    """The parser."""
    parser = argparse.ArgumentParser(add_help=True)

    parser_grp = parser.add_argument_group('Arguments')

    parser.add_argument('-i', '--inputfile',
                        help="Path to the GTF file. Default to STDIN",
                        default=sys.stdin,
                        metavar="GTF",
                        type=FileWithExtension('r',
                                               valid_extensions='\.[Gg][Tt][Ff](\.[Gg][Zz])?$'))

    parser.add_argument('-o', '--outputfile',
                        help="Output file.",
                        default=sys.stdout,
                        metavar="GTF",
                        type=FileWithExtension('w',
                                               valid_extensions='\.[Gg][Tt][Ff]$'))

    parser_grp.add_argument('-r', '--from-region-type',
                            help="What is region to consider for each gene.",
                            choices=['tss', 'tts', 'gene'],
                            default="tss",
                            type=str,
                            required=False)

    parser_grp.add_argument('-nb', '--nb-neighbors',
                            help="The size of the neighborhood.",
                            default=1,
                            type=int,
                            required=False)

    parser_grp.add_argument('-t', '--to-region-type',
                            help="What is region to consider for each closest gene.",
                            choices=['tss', 'tts', 'gene'],
                            default="tss",
                            type=str,
                            required=False)

    parser_grp.add_argument('-s', '--same-strandedness',
                            help="Require same strandedness",
                            action='store_true',
                            required=False)

    parser_grp.add_argument('-S', '--diff-strandedness',
                            help="Require different strandedness",
                            action='store_true',
                            required=False)

    parser_grp.add_argument('-f', '--text-format',
                            help="Return a text format.",
                            action="store_true")

    parser_grp.add_argument('-H', '--no-header',
                            help="Don't print the header line.",
                            action="store_true",
                            required=False)

    parser_grp.add_argument('-k', '--collapse',
                            help="Unwrap. Don't use comma. Print closest genes line by line.",
                            action="store_true",
                            required=False)

    parser_grp.add_argument('-id', '--identifier',
                            help="The key used as gene identifier.",
                            choices=["gene_id", "gene_name"],
                            default="gene_id",
                            required=False)

    return parser


def closest_genes(
        inputfile=None,
        outputfile=None,
        from_region_type=None,
        no_header=False,
        nb_neighbors=1,
        to_region_type=None,
        same_strandedness=False,
        diff_strandedness=False,
        text_format=False,
        identifier="gene_id",
        collapse=False,
        tmp_dir=None,
        logger_file=None,
        verbosity=0):
    """
    Find the n closest genes for each gene.
    """

    if same_strandedness and diff_strandedness:
        message("--same-strandedness and --diff-strandedness are "
                "mutually exclusive.",
                type="ERROR")

    # ----------------------------------------------------------------------
    # load GTF
    # ----------------------------------------------------------------------

    gtf = GTF(inputfile)
    gn_gtf = gtf.select_by_key("feature", "gene")

    if len(gn_gtf) == 0:
        message("No gene feature found. Please use convert_ensembl.",
                type="ERROR")
    if nb_neighbors >= (len(gn_gtf) - 1):
        message("Two much neighbors",
                type="ERROR")

    all_ids = gn_gtf.extract_data(identifier, as_list=True, no_na=False)

    if "." in all_ids:
        message("Some identifiers are undefined ('.').",
                type="ERROR")

    if len(all_ids) == 0:
        message("The identifier was not found.",
                type="ERROR")

    # ----------------------------------------------------------------------
    # load GTF and requested regions (for source/'from' transcript)
    # ----------------------------------------------------------------------

    if from_region_type == 'tss':
        from_regions = gn_gtf.get_5p_end(feat_type="gene",
                                         name=[identifier],
                                         ).cut([0, 1, 2,
                                                3, 4, 5]).sort()
    elif from_region_type == 'tts':
        from_regions = gn_gtf.get_3p_end(feat_type="gene",
                                         name=[identifier],
                                         ).cut([0, 1, 2,
                                                3, 4, 5]).sort()
    elif from_region_type == 'gene':
        from_regions = gn_gtf.to_bed(name=[identifier],
                                     ).cut([0, 1, 2,
                                            3, 4, 5]).sort()
    else:
        message("Unknown type.", type="ERROR")

    # ----------------------------------------------------------------------
    # load GTF and requested regions (for dest/'to' transcript)
    # ----------------------------------------------------------------------

    if to_region_type == 'tss':
        to_regions = gn_gtf.get_5p_end(feat_type="gene",
                                       name=[identifier],
                                       ).cut([0, 1, 2,
                                              3, 4, 5]).sort()
    elif to_region_type == 'tts':
        to_regions = gn_gtf.get_3p_end(feat_type="gene",
                                       name=[identifier],
                                       ).cut([0, 1, 2,
                                              3, 4, 5]).sort()

    elif to_region_type == 'gene':
        to_regions = gn_gtf.to_bed(name=[identifier],
                                   ).cut([0, 1, 2,
                                          3, 4, 5]).sort()
    else:
        message("Unknown type.", type="ERROR")

    strands = gn_gtf.extract_data(identifier + ",strand",
                                  as_dict_of_values=True)

    # ----------------------------------------------------------------------
    # Search closest genes
    # ----------------------------------------------------------------------

    gene_closest = defaultdict(list)
    gene_closest_dist = defaultdict(list)

    closest_bo = from_regions.closest(b=to_regions,
                                      k=nb_neighbors,
                                      N=True,
                                      s=same_strandedness,
                                      S=diff_strandedness,
                                      d=True)

    for i in closest_bo:
        gene_closest[i[3]] += [i[9]]
        gene_closest_dist[i[3]] += [i[12]]

    if not text_format:

        if len(gene_closest):
            gtf = gtf.add_attr_from_dict(feat="gene",
                                         key=identifier,
                                         a_dict=gene_closest,
                                         new_key="closest_gn")

            gtf = gtf.add_attr_from_dict(feat="gene",
                                         key=identifier,
                                         a_dict=gene_closest_dist,
                                         new_key="closest_dist")

        gtf.write(outputfile)

    else:
        if not no_header:
            outputfile.write("genes\tclosest_genes\tdistances\n")

        for gene in gene_closest:

            if not collapse:

                outputfile.write("\t".join([gene,
                                            ",".join(gene_closest[gene]),
                                            ",".join(gene_closest_dist[gene])]) + "\n")

            else:

                for closest, dist in zip(gene_closest[gene],
                                         gene_closest_dist[gene]):
                    outputfile.write("\t".join([gene,
                                                closest,
                                                dist]) + "\n")

    close_properly(outputfile, inputfile)


def main():
    """The main function."""
    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    closest_genes(**args)


if __name__ == '__main__':
    main()

else:

    test = """
    #closest_genes: check whole file
    @test "closest_genes_1" {
     result=`gtftk get_example | gtftk closest_genes -f | md5sum-lite | sed 's/ .*//'`
      [ "$result" = "6314536371950e99a3a6bcd97a289ff4" ]
    }
        
    #closest_genes: check dist
    @test "closest_genes_2" {
     result=`gtftk get_example | gtftk closest_genes -f | grep ^G0010 | perl -npe 's/\\t/,/g'`
      [ "$result" = "G0010,G0002,4" ]
    }

    #closest_genes: check dist
    @test "closest_genes_3" {
     result=`gtftk get_example | gtftk closest_genes -f | grep ^G0002     | perl -npe 's/\\t/,/g'`
      [ "$result" = "G0002,G0010,4" ]
    }

    #closest_genes: check dist
    @test "closest_genes_4" {
     result=`gtftk get_example | gtftk closest_genes -n 2 -f | grep ^G0010 | perl -npe 's/\\t/,/g'`
      [ "$result" = "G0010,G0002,G0008,4,46" ]
    }

    #closest_genes: check dist
    @test "closest_genes_5" {
     result=`gtftk get_example | gtftk closest_genes -n 3 -f | grep ^G0006 | perl -npe 's/\\t/,/g'`
      [ "$result" = "G0006,G0005,G0009,G0003,12,21,26" ]
    }

    #closest_genes: check -r/-t
    @test "closest_genes_6" {
     result=`gtftk get_example | gtftk closest_genes -n 3 -t gene  -f| grep ^G0006 | perl -npe 's/\\t/,/g'`
      [ "$result" = "G0006,G0005,G0003,G0009,0,15,21" ]
    }

    #closest_genes: check -r/-t
    @test "closest_genes_7" {
     result=`gtftk get_example | gtftk closest_genes -n 3  -t tts -f | grep ^G0006 | perl -npe 's/\\t/,/g'`
      [ "$result" = "G0006,G0005,G0003,G0009,2,15,32" ]
    }

    #closest_genes: check -r/-t
    @test "closest_genes_8" {
     result=`gtftk get_example | gtftk closest_genes -n 3  -t tts -r tts -f | grep ^G0006 | perl -npe 's/\\t/,/g'`
      [ "$result" = "G0006,G0005,G0009,G0003,11,19,28" ]
    }

    #closest_genes: check -r/-t
    @test "closest_genes_9" {
     result=`gtftk get_example | gtftk closest_genes -n 3  -t gene -r gene -f | grep ^G0006 | perl -npe 's/\\t/,/g'`
      [ "$result" = "G0006,G0005,G0009,G0003,0,8,15" ]
    }

    #closest_genes: check -r/-t
    @test "closest_genes_10" {
     result=`gtftk get_example |  bedtools sort | gtftk closest_genes -n 3  -t gene -r gene -f | md5sum-lite | sed 's/ .*//'`
      [ "$result" = "6a4df0a85b8e997649db440bdda8e67e" ]
    }

    @test "closest_genes_11" {
     result=`gtftk get_example |  perl -MList::Util -e 'print List::Util::shuffle <>' | gtftk closest_genes -n 3  -t gene -r gene -f | grep ^G0006 | perl -npe 's/\\t/,/g'`
      [ "$result" = "G0006,G0005,G0009,G0003,0,8,15" ]
    }
    
    """

    CMD = CmdObject(name="closest_genes",
                    message="Find the n closest genes for each transcript.",
                    parser=make_parser(),
                    fun=closest_genes,
                    updated=__updated__,
                    desc=__doc__,
                    test=test,
                    group="annotation",
                    notes=__notes__)