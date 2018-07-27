#!/usr/bin/env python
from __future__ import print_function

import argparse
import errno
import sys
from collections import defaultdict

from pygtftk.arg_formatter import FileWithExtension
from pygtftk.cmd_object import CmdObject
from pygtftk.gtf_interface import GTF
from pygtftk.utils import close_properly
from pygtftk.utils import message

__updated__ = "2018-01-20"
__doc__ = """
 Computes the distance between TSSs of pairs of gene transcripts.
"""

__notes__ = """
 -- The tss_num_1/tss_num_1 columns contains the numbering of TSSs (transcript_id_1 and transcript_id_2 respectively) for each gene.
 -- Numering starts from 1 (most 5' TSS) to the number of different TSS coordinates.
 -- Thus two or more transcripts will have the same tss_num if they share a TSS.
"""


def make_parser():
    """The parser."""
    parser = argparse.ArgumentParser(add_help=True)

    parser_grp = parser.add_argument_group('Arguments')

    parser_grp.add_argument('-i', '--inputfile',
                            help="Path to the GTF file. Default to STDIN.",
                            default=sys.stdin,
                            metavar="GTF",
                            required=False,
                            type=FileWithExtension('r',
                                                   valid_extensions='\.[Gg][Tt][Ff](\.[Gg][Zz])?$'))

    parser_grp.add_argument('-o', '--outputfile',
                            help="Output file.",
                            default=sys.stdout,
                            metavar="TXT",
                            type=FileWithExtension('w',
                                                   valid_extensions=('\.[Tt][Xx][Tt]',
                                                                     '\.[Cc][Ss][Vv]',
                                                                     '\.[Tt][Aa][Bb]',
                                                                     '\.[Tt][Ss][Vv]',
                                                                     '\.[Cc][Oo][Vv]')))

    return parser


def tss_dist(
        inputfile=None,
        outputfile=None,
        tmp_dir=None,
        logger_file=None,
        verbosity=0):
    """
    Computes the distance between TSS of gene transcripts.
    """

    gtf = GTF(inputfile, check_ensembl_format=True)

    gn_tss_dist = defaultdict(dict)

    message("Getting TSSs.")
    tss = gtf.get_tss(name=["transcript_id", "gene_id"], as_dict=True)

    for k in tss:
        tx_id, gn_id = k.split("|")
        gn_tss_dist[gn_id][tx_id] = int(tss[k])

    gn_to_tx_to_tss = gtf.get_gn_to_tx(as_dict_of_dict=True)

    message("Computing distances.")

    outputfile.write("\t".join(["gene_id",
                                "transcript_id_1",
                                "transcript_id_2",
                                "dist",
                                "tss_num_1",
                                "tss_num_2"]) + "\n")
    try:
        for gn_id in gn_tss_dist:
            tx_list = gn_tss_dist[gn_id].keys()
            for i in range(len(tx_list) - 1):

                for j in range(i + 1, len(tx_list)):
                    dist = str(abs(gn_tss_dist[gn_id][tx_list[i]] - gn_tss_dist[gn_id][tx_list[j]]))
                    tss_1 = gn_to_tx_to_tss[gn_id][tx_list[i]]
                    tss_2 = gn_to_tx_to_tss[gn_id][tx_list[j]]

                    if tss_1 < tss_2:
                        str_out = "\t".join([gn_id,
                                             tx_list[i],
                                             tx_list[j],
                                             dist,
                                             str(tss_1),
                                             str(tss_2)]) + "\n"
                        outputfile.write(str_out)
                    else:
                        str_out = "\t".join([gn_id,
                                             tx_list[j],
                                             tx_list[i],
                                             dist,
                                             str(tss_2),
                                             str(tss_1)]) + "\n"
                        outputfile.write(str_out)
    except IOError as e:
        if e.errno == errno.EPIPE:
            message("Received a boken pipe signal", type="WARNING")

    close_properly(outputfile, inputfile)


def main():
    """The main function."""
    myparser = make_parser()
    args = myparser.parse_args()
    args = dict(args.__dict__)
    tss_dist(**args)


if __name__ == '__main__':
    main()

else:

    test = """

    #tss_dist
    @test "tss_dist_1" {
     result=`gtftk get_example  | gtftk tss_dist| wc -l`
      [ "$result" -eq 6 ]
    }

    @test "tss_dist_2" {
     result=`gtftk get_example -d simple_04| gtftk tss_dist| grep G0004T002 | grep G0004T001| cut -f 4 `
      [ "$result" -eq 8 ]
    }
    
    @test "tss_dist_3" {
     result=`gtftk get_example -d mini_real | gtftk tss_dist | grep ENSG00000097007 | cut -f4 | perl -npe 's/\\n/,/' `
      [ "$result" = "121086,121120,34," ]
    }    
    
    """

    CMD = CmdObject(name="tss_dist",
                    message="Computes the distance between TSS of gene transcripts.",
                    parser=make_parser(),
                    fun=tss_dist,
                    updated=__updated__,
                    notes=__notes__,
                    desc=__doc__,
                    group="information",
                    test=test)
