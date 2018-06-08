from concurrent import futures
import sys
import time
import grpc
import loompy as lp
import os
import re
import numpy as np
import pandas as pd
import shutil
import json
import zlib
import base64
import threading
import pickle
import uuid
from collections import OrderedDict, defaultdict
from functools import lru_cache
from itertools import compress
from pathlib import Path

from scopeserver.dataserver.modules.gserver import s_pb2
from scopeserver.dataserver.modules.gserver import s_pb2_grpc
from scopeserver.utils import SysUtils as su
from scopeserver.utils import LoomFileHandler as lfh
from scopeserver.utils import DataFileHandler as dfh
from scopeserver.utils import GeneSetEnrichment as _gse

from pyscenic.genesig import GeneSignature
from pyscenic.aucell import create_rankings, enrichment, enrichment4cells

_ACTIVE_SESSIONS_LIMIT = 25
_MOUSE_EVENTS_THRESHOLD = 1
_LOWER_LIMIT_RGB = 0
_UPPER_LIMIT_RGB = 225
_NO_EXPR_RGB = 166

BIG_COLOR_LIST = ["ff0000", "ffc480", "149900", "307cbf", "d580ff", "cc0000", "bf9360", "1d331a", "79baf2", "deb6f2",
                  "990000", "7f6240", "283326", "2d4459", "8f00b3", "4c0000", "ccb499", "00f220", "accbe6", "520066",
                  "330000", "594f43", "16591f", "697c8c", "290033", "cc3333", "e59900", "ace6b4", "262d33", "ee00ff",
                  "e57373", "8c5e00", "2db350", "295ba6", "c233cc", "994d4d", "664400", "336641", "80b3ff", "912699",
                  "663333", "332200", "86b392", "4d6b99", "3d1040", "bf8f8f", "cc9933", "4d6653", "202d40", "c566cc",
                  "8c6969", "e5bf73", "008033", "0044ff", "944d99", "664d4d", "594a2d", "39e67e", "00144d", "a37ca6",
                  "f2553d", "403520", "30bf7c", "3d6df2", "ff80f6", "a63a29", "ffeabf", "208053", "2d50b3", "73396f",
                  "bf6c60", "736956", "134d32", "13224d", "4d264a", "402420", "f2c200", "53a67f", "7391e6", "735671",
                  "ffc8bf", "8c7000", "003322", "334166", "40303f", "ff4400", "ccad33", "3df2b6", "a3b1d9", "ff00cc",
                  "b23000", "594c16", "00bf99", "737d99", "8c0070", "7f2200", "ffe680", "66ccb8", "393e4d", "331a2e",
                  "591800", "b2a159", "2d5950", "00138c", "ffbff2", "330e00", "7f7340", "204039", "364cd9", "b30077",
                  "ff7340", "ffee00", "b6f2e6", "1d2873", "40002b", "cc5c33", "403e20", "608079", "404880", "e639ac",
                  "994526", "bfbc8f", "00998f", "1a1d33", "731d56", "f29979", "8c8a69", "00736b", "0000f2", "ff80d5",
                  "8c5946", "778000", "39e6da", "0000d9", "a6538a", "59392d", "535900", "005359", "0000bf", "f20081",
                  "bf9c8f", "3b4000", "003c40", "2929a6", "660036", "735e56", "ced936", "30b6bf", "bfbfff", "bf8fa9",
                  "403430", "fbffbf", "23858c", "8273e6", "d90057", "f26100", "ccff00", "79eaf2", "332d59", "a60042",
                  "bf4d00", "cfe673", "7ca3a6", "14004d", "bf3069", "331400", "8a994d", "394b4d", "170d33", "8c234d",
                  "ff8c40", "494d39", "005266", "a799cc", "bf6086", "995426", "a3d936", "39c3e6", "7d7399", "804059",
                  "733f1d", "739926", "23778c", "290066", "59434c", "f2aa79", "88ff00", "0d2b33", "8c40ff", "b20030",
                  "b27d59", "3d7300", "59a1b3", "622db3", "7f0022", "7f5940", "294d00", "acdae6", "2a134d", "40101d",
                  "33241a", "4e6633", "566d73", "7453a6", "f27999", "ffd9bf", "bfd9a3", "00aaff", "4c4359", "4d2630",
                  "8c7769", "92a67c", "006699", "2b2633", "ffbfd0", "ff8800", "52cc00", "002b40", "6d00cc", "99737d",
                  "a65800", "234010", "3399cc", "4b008c", "33262a", "663600", "a1ff80", "86a4b3", "9c66cc", "7f0011",
                  "331b00", "79bf60", "007ae6", "583973", "f23d55", "cc8533", "518040", "003059", "312040", "59161f",
                  "4c3213", "688060", "001b33", "69238c", "bf606c"]

hexarr = np.vectorize('{:02x}'.format)

uploadedLooms = defaultdict(lambda: set())

class SCope(s_pb2_grpc.MainServicer):

    app_name = 'SCope'
    app_author = 'Aertslab'
    app_version = '1.0'

    def __init__(self):
        self.dfh = dfh.DataFileHandler(dev_env=SCope.dev_env)
        self.lfh = lfh.LoomFileHandler()

        self.dfh.load_gene_mappings()
        self.dfh.set_global_data()
        self.lfh.set_global_data()
        self.dfh.read_UUID_db()

    def update_global_data(self):
        self.dfh.set_global_data()
        self.lfh.set_global_data()

    @staticmethod
    def compress_str_array(str_arr):
        print("Compressing... ")
        str_array_size = sys.getsizeof(str_arr)
        str_array_joint = bytes(''.join(str_arr), 'utf-8')
        str_array_joint_compressed = zlib.compress(str_array_joint, 1)
        str_array_joint_compressed_size = sys.getsizeof(str_array_joint_compressed)
        savings_percent = 1-str_array_joint_compressed_size/str_array_size
        print("Saving "+"{:.2%} of space".format(savings_percent))
        return str_array_joint_compressed

    @lru_cache(maxsize=16)
    def build_searchspace(self, loom, cross_species=''):
        start_time = time.time()
        species, gene_mappings = loom.infer_species()
        if loom.has_meta_data():
            meta_data = loom.get_meta_data()

        def add_element(search_space, elements, element_type):
            if type(elements) != str:
                for element in elements:
                    if element_type == 'gene' and cross_species == '' and len(gene_mappings) > 0:
                        if gene_mappings[element] != element:
                            search_space[('{0}'.format(str(element)).casefold(), element, element_type)] = gene_mappings[element]
                        else:
                            search_space[(element.casefold(), element, element_type)] = element
                    else:
                        search_space[(element.casefold(), element, element_type)] = element
            else:
                search_space[(elements.casefold(), elements, element_type)] = elements
            return search_space

        search_space = {}

        # Include all features (clusterings, regulons, annotations, ...) into the search space
        # if and only if the query is not a cross-species query
        if cross_species == 'hsap' and species == 'dmel':
            search_space = add_element(search_space=search_space, elements=self.dfh.hsap_to_dmel_mappings.keys(), element_type='gene')
        elif cross_species == 'mmus' and species == 'dmel':
            search_space = add_element(search_space=search_space, elements=self.dfh.mmus_to_dmel_mappings.keys(), element_type='gene')
        else:
            if len(gene_mappings) > 0:
                genes = set(loom.get_genes())
                shrink_mappings = set([x for x in self.dfh.dmel_mappings.keys() if x in genes or self.dfh.dmel_mappings[x] in genes])
                # search_space = add_element(search_space, SCope.dmel_mappings.keys(), 'gene')
                search_space = add_element(search_space=search_space, elements=shrink_mappings, element_type='gene')
            else:
                search_space = add_element(search_space=search_space, elements=loom.get_genes(), element_type='gene')

            # Add clusterings to the search space if present in .loom
            if loom.has_md_clusterings():
                for clustering in meta_data['clusterings']:
                    allClusters = ['All Clusters']
                    for cluster in clustering['clusters']:
                        allClusters.append(cluster['description'])
                    search_space = add_element(search_space=search_space, elements=allClusters, element_type='Clustering: {0}'.format(clustering['name']))
            
            # Add regulons to the search space if present in .loom
            if loom.has_regulons_AUC():
                search_space = add_element(search_space=search_space, elements=loom.get_regulons_AUC().dtype.names, element_type='regulon')
            else:
                print("No regulons found in the .loom file.")

            # Add annotations to the search space if present in .loom
            if loom.has_md_annotations():
                annotations = []
                for annotation in meta_data['annotations']:
                    annotations.append(annotation['name'])
                search_space = add_element(search_space, annotations, 'annotation')

        print("Debug: %s seconds elapsed making search space ---" % (time.time() - start_time))
        #  Dict, keys = tuple(elementCF, element, elementName), values = element/translastedElement
        return search_space

    @lru_cache(maxsize=256)
    def get_features(self, loom, query):
        print(query)
        if query.startswith('hsap\\'):
            searchSpace = self.build_searchspace(loom=loom, cross_species='hsap')
            crossSpecies = 'hsap'
            query = query[5:]
        elif query.startswith('mmus\\'):
            searchSpace = self.build_searchspace(loom=loom, cross_species='mmus')
            crossSpecies = 'mmus'
            query = query[5:]
        else:
            searchSpace = self.build_searchspace(loom=loom)
            crossSpecies = ''
        print(query)

        # Filter the genes by the query

        # Allow caps innsensitive searching, minor slowdown
        start_time = time.time()
        res = []

        queryCF = query.casefold()
        res = [x for x in searchSpace.keys() if queryCF in x[0]]

        for n, r in enumerate(res):
            if query in r[0]:
                r = res.pop(n)
                res = [r] + res
        for n, r in enumerate(res):
            if r[0].startswith(queryCF):
                r = res.pop(n)
                res = [r] + res
        for n, r in enumerate(res):
            if r[0] == queryCF:
                r = res.pop(n)
                res = [r] + res
        for n, r in enumerate(res):
            if r[1] == query:
                r = res.pop(n)
                res = [r] + res

        # These structures are a bit messy, but still fast
        # r = (elementCF, element, elementName)
        # dg = (drosElement, %match)
        # searchSpace[r] = translastedElement
        collapsedResults = OrderedDict()
        if crossSpecies == '':
            for r in res:
                if (searchSpace[r], r[2]) not in collapsedResults.keys():
                    collapsedResults[(searchSpace[r], r[2])] = [r[1]]
                else:
                    collapsedResults[(searchSpace[r], r[2])].append(r[1])
        elif crossSpecies == 'hsap':
            for r in res:
                for dg in self.dfh.hsap_to_dmel_mappings[searchSpace[r]]:
                    if (dg[0], r[2]) not in collapsedResults.keys():
                        collapsedResults[(dg[0], r[2])] = (r[1], dg[1])
        elif crossSpecies == 'mmus':
            for r in res:
                for dg in self.dfh.mmus_to_dmel_mappings[searchSpace[r]]:
                    if (dg[0], r[2]) not in collapsedResults.keys():
                        collapsedResults[(dg[0], r[2])] = (r[1], dg[1])

        descriptions = []
        if crossSpecies == '':
            for r in collapsedResults.keys():
                synonyms = sorted([x for x in collapsedResults[r]])
                try:
                    synonyms.remove(r[0])
                except ValueError:
                    pass
                if len(synonyms) > 0:
                    descriptions.append('Synonym of: {0}'.format(', '.join(synonyms)))
                else:
                    descriptions.append('')
        elif crossSpecies == 'hsap':
            for r in collapsedResults.keys():
                descriptions.append('Orthologue of {0}, {1:.2f}% identity (Human -> Drosophila)'.format(collapsedResults[r][0], collapsedResults[r][1]))
        elif crossSpecies == 'mmus':
            for r in collapsedResults.keys():
                descriptions.append('Orthologue of {0}, {1:.2f}% identity (Mouse -> Drosophila)'.format(collapsedResults[r][0], collapsedResults[r][1]))
        # if mapping[result] != result: change title and description to indicate synonym

        print("Debug: " + str(len(res)) + " genes matching '" + query + "'")
        print("Debug: %s seconds elapsed ---" % (time.time() - start_time))
        res = {'feature': [r[0] for r in collapsedResults.keys()],
               'featureType': [r[1] for r in collapsedResults.keys()],
               'featureDescription': descriptions}
        return res

    def compressHexColor(self, a):
        a = int(a, 16)
        a_hex3d = hex(a >> 20 << 8 | a >> 8 & 240 | a >> 4 & 15)
        return a_hex3d.replace("0x", "")

    @staticmethod
    def get_vmax(vals):
        maxVmax = max(vals)
        vmax = np.percentile(vals, 99)
        if vmax == 0 and max(vals) != 0:
            vmax = max(vals)
        if vmax == 0:
            vmax = 0.01
        return vmax, maxVmax

    def getVmax(self, request, context):
        vmax = np.zeros(3)
        maxVmax = np.zeros(3)

        for n, feature in enumerate(request.feature):
            fVmax = 0
            fMaxVmax = 0
            if feature != '':
                for loomFilePath in request.loomFilePath:
                    lVmax = 0
                    lMaxVmax = 0
                    loom = self.lfh.get_loom(loom_file_path=loomFilePath)
                    if request.featureType[n] == 'gene':
                            vals, cellIndices = loom.get_gene_expression(
                                gene_symbol=feature,
                                log_transform=request.hasLogTransform,
                                cpm_normalise=request.hasCpmTransform)
                            lVmax, lMaxVmax = SCope.get_vmax(vals)
                    if request.featureType[n] == 'regulon':
                            vals, cellIndices = loom.get_auc_values(regulon=feature)
                            lVmax, lMaxVmax = SCope.get_vmax(vals)
                    if lVmax > fVmax:
                        fVmax = lVmax
                if lMaxVmax > fMaxVmax:
                    fMaxVmax = lMaxVmax
            vmax[n] = fVmax
            maxVmax[n] = fMaxVmax
        return s_pb2.VmaxReply(vmax=vmax, maxVmax=maxVmax)

    def getCellColorByFeatures(self, request, context):
        start_time = time.time()
        try:
            loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        except ValueError:
            return
        meta_data = loom.get_meta_data()
        n_cells = loom.get_nb_cells()
        features = []
        hex_vec = []
        vmax = np.zeros(3)
        maxVmax = np.zeros(3)
        cellIndices = list(range(n_cells))

        for n, feature in enumerate(request.feature):
            if request.featureType[n] == 'gene':
                if feature != '':
                    vals, cellIndices = loom.get_gene_expression(
                        gene_symbol=feature,
                        log_transform=request.hasLogTransform,
                        cpm_normalise=request.hasCpmTransform,
                        annotation=request.annotation,
                        logic=request.logic)
                    if request.vmax[n] != 0.0:
                        vmax[n] = request.vmax[n]
                    else:
                        vmax[n], maxVmax[n] = SCope.get_vmax(vals)
                    # vals = np.round((vals / vmax[n]) * 225)
                    vals = vals / vmax[n]
                    vals = (((_UPPER_LIMIT_RGB - _LOWER_LIMIT_RGB) * (vals - min(vals))) / (1 - min(vals))) + _LOWER_LIMIT_RGB
                    features.append([x if x <= _UPPER_LIMIT_RGB else _UPPER_LIMIT_RGB for x in vals])
                else:
                    features.append(np.zeros(n_cells))
            elif request.featureType[n] == 'regulon':
                if feature != '':
                    vals, cellIndices = loom.get_auc_values(regulon=feature,
                                                            annotation=request.annotation,
                                                            logic=request.logic)
                    if request.vmax[n] != 0.0:
                        vmax[n] = request.vmax[n]
                    else:
                        vmax[n], maxVmax[n] = SCope.get_vmax(vals)
                    if request.scaleThresholded:
                        vals = ([auc if auc >= request.threshold[n] else 0 for auc in vals])
                        # vals = np.round((vals / vmax[n]) * 225)
                        vals = vals / vmax[n]
                        vals = (((_UPPER_LIMIT_RGB - _LOWER_LIMIT_RGB) * (vals - min(vals))) / (1 - min(vals))) + _LOWER_LIMIT_RGB
                        features.append([x if x <= _UPPER_LIMIT_RGB else _UPPER_LIMIT_RGB for x in vals])
                    else:
                        features.append([_UPPER_LIMIT_RGB if auc >= request.threshold[n] else 0 for auc in vals])
                else:
                    features.append(np.zeros(n_cells))
            elif request.featureType[n] == 'annotation':
                md_annotation_values = loom.get_meta_data_annotation_by_name(name=feature)["values"]
                ca_annotation = loom.get_annotation_by_name(name=feature)
                ca_annotation_as_int = list(map(lambda x: md_annotation_values.index(x), ca_annotation))
                num_annotations = max(ca_annotation_as_int)
                if num_annotations <= len(BIG_COLOR_LIST):
                    hex_vec = list(map(lambda x: BIG_COLOR_LIST[x], ca_annotation_as_int))
                else:
                    raise ValueError("The annotation {0} has too many unique values.".format(feature))
                return s_pb2.CellColorByFeaturesReply(color=hex_vec, 
                                                      vmax=vmax,
                                                      legend=s_pb2.ColorLegend(values=md_annotation_values, colors=BIG_COLOR_LIST[:len(md_annotation_values)]))
            elif request.featureType[n].startswith('Clustering: '):
                for clustering in meta_data['clusterings']:
                    if clustering['name'] == re.sub('^Clustering: ', '', request.featureType[n]):
                        clusteringID = str(clustering['id'])
                        if request.feature[n] == 'All Clusters':
                            numClusters = max(loom.get_clustering_by_id(clusteringID))
                            if numClusters <= 245:
                                for i in loom.get_clustering_by_id(clusteringID):
                                    hex_vec.append(BIG_COLOR_LIST[i])
                            else:
                                interval = int(16581375 / numClusters)
                                hex_vec = [hex(I)[2:].zfill(6) for I in range(0, numClusters, interval)]
                            if len(request.annotation) > 0:
                                cellIndices = loom.get_anno_cells(annotations=request.annotation, logic=request.logic)
                                hex_vec = np.array(hex_vec)[cellIndices]
                            return s_pb2.CellColorByFeaturesReply(color=hex_vec, vmax=vmax)
                        else:
                            for cluster in clustering['clusters']:
                                if request.feature[n] == cluster['description']:
                                    clusterID = int(cluster['id'])
                clusterIndices = loom.get_clustering_by_id(clusteringID) == clusterID
                clusterCol = np.array([_UPPER_LIMIT_RGB if x else 0 for x in clusterIndices])
                if len(request.annotation) > 0:
                    cellIndices = loom.get_anno_cells(annotations=request.annotation, logic=request.logic)
                    clusterCol = clusterCol[cellIndices]
                features.append(clusterCol)
            else:
                features.append([_LOWER_LIMIT_RGB for n in range(n_cells)])

        if len(features) > 0 and len(hex_vec) == 0:
            hex_vec = ["XXXXXX" if r == g == b == 0 # previously null: ???
                       else "{0:02x}{1:02x}{2:02x}".format(int(r), int(g), int(b))
                       for r, g, b in zip(features[0], features[1], features[2])]

        # Compress
        comp_start_time = time.time()
        hex_vec_compressed = SCope.compress_str_array(str_arr=hex_vec)
        print("Debug: %s seconds elapsed (compression) ---" % (time.time() - comp_start_time))

        print("Debug: %s seconds elapsed ---" % (time.time() - start_time))
        return s_pb2.CellColorByFeaturesReply(color=None,
                                              compressedColor=hex_vec_compressed,
                                              hasAddCompressionLayer=True,
                                              vmax=vmax,
                                              maxVmax=maxVmax,
                                              cellIndices=cellIndices)

    def getCellAUCValuesByFeatures(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        vals, cellIndices = loom.get_auc_values(regulon=request.feature[0])
        return s_pb2.CellAUCValuesByFeaturesReply(value=vals)

    def getCellMetaData(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        cellIndices = request.cellIndices
        if len(cellIndices) == 0:
            cellIndices = list(range(loom.get_nb_cells()))

        cellClusters = []
        for clustering_id in request.clusterings:
            if clustering_id != '':
                cellClusters.append(loom.get_clustering_by_id(clustering_id=clustering_id)[cellIndices])
        geneExp = []
        for gene in request.selectedGenes:
            if gene != '':
                vals, _ = loom.get_gene_expression(gene_symbol=gene,
                                                   log_transform=request.hasLogTransform,
                                                   cpm_normalise=request.hasCpmTransform)
                geneExp.append(vals[cellIndices])
        aucVals = []
        for regulon in request.selectedRegulons:
            if regulon != '':
                vals, _ = aucVals.append(loom.get_auc_values(regulon=regulon))
                aucVals.append(vals[[cellIndices]])
        annotations = []
        for anno in request.annotations:
            if anno != '':
                annotations.append(loom.get_annotation_by_name(name=anno)[cellIndices])

        return s_pb2.CellMetaDataReply(clusterIDs=[s_pb2.CellClusters(clusters=x) for x in cellClusters],
                                       geneExpression=[s_pb2.FeatureValues(features=x) for x in geneExp],
                                       aucValues=[s_pb2.FeatureValues(features=x) for x in aucVals],
                                       annotations=[s_pb2.CellAnnotations(annotations=x) for x in annotations])

    def getFeatures(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        f = self.get_features(loom=loom, query=request.query)
        return s_pb2.FeatureReply(feature=f['feature'], featureType=f['featureType'], featureDescription=f['featureDescription'])

    def getCoordinates(self, request, context):
        # request content
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        c = loom.get_coordinates(coordinatesID=request.coordinatesID,
                                 annotation=request.annotation,
                                 logic=request.logic)
        return s_pb2.CoordinatesReply(x=c["x"], y=c["y"], cellIndices=c["cellIndices"])

    def getRegulonMetaData(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        regulon_genes = loom.get_regulon_genes(regulon=request.regulon)
        
        if len(regulon_genes) == 0:
            print("Something is wrong in the loom file: no regulon found!")

        meta_data = loom.get_meta_data()
        for regulon in meta_data['regulonThresholds']:
            if regulon['regulon'] == request.regulon:
                autoThresholds = []
                for threshold in regulon['allThresholds'].keys():
                    autoThresholds.append({"name": threshold, "threshold": regulon['allThresholds'][threshold]})
                defaultThreshold = regulon['defaultThresholdName']
                motifName = os.path.basename(regulon['motifData'])
                break

        regulon = {"genes": regulon_genes,
                   "autoThresholds": autoThresholds,
                   "defaultThreshold": defaultThreshold,
                   "motifName": motifName
                   }

        return s_pb2.RegulonMetaDataReply(regulonMeta=regulon)

    def getMarkerGenes(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        genes = loom.get_cluster_marker_genes(clustering_id=request.clusteringID, cluster_id=request.clusterID)
        # Filter the MD clusterings by ID
        md_clustering = loom.get_meta_data_clustering_by_id(id=request.clusteringID)
        cluster_marker_metrics = None

        if "clusterMarkerMetrics" in md_clustering.keys():
            md_cmm = md_clustering["clusterMarkerMetrics"]
            def create_cluster_marker_metric(metric):
                cluster_marker_metrics = loom.get_cluster_marker_metrics(clustering_id=request.clusteringID, cluster_id=request.clusterID, metric_accessor=metric["accessor"])
                return s_pb2.MarkerGenesMetric(accessor=metric["accessor"],
                                               name=metric["name"],
                                               description=metric["description"],
                                               values=cluster_marker_metrics)

            cluster_marker_metrics = list(map(create_cluster_marker_metric, md_cmm))

        return(s_pb2.MarkerGenesReply(genes=genes, metrics=cluster_marker_metrics))

    def getMyGeneSets(self, request, context):
        userDir = dfh.DataFileHandler.get_data_dir_path_by_file_type('GeneSet', UUID=request.UUID)
        if not os.path.isdir(userDir):
            for i in ['Loom', 'GeneSet', 'LoomAUCellRankings']:
                os.mkdir(os.path.join(self.dfh.get_data_dirs()[i]['path'], request.UUID))

        geneSetsToProcess = sorted(self.dfh.get_gobal_sets()) + sorted([os.path.join(request.UUID, x) for x in os.listdir(userDir)])
        gene_sets = [s_pb2.MyGeneSet(geneSetFilePath=f, geneSetDisplayName=os.path.splitext(os.path.basename(f))[0]) for f in geneSetsToProcess]
        return s_pb2.MyGeneSetsReply(myGeneSets=gene_sets)

    def getMyLooms(self, request, context):
        my_looms = []
        userDir = dfh.DataFileHandler.get_data_dir_path_by_file_type('Loom', UUID=request.UUID)
        if not os.path.isdir(userDir):
            for i in ['Loom', 'GeneSet', 'LoomAUCellRankings']:
                os.mkdir(os.path.join(self.dfh.get_data_dirs()[i]['path'], request.UUID))

        self.update_global_data()

        loomsToProcess = sorted(self.lfh.get_global_looms()) + sorted([os.path.join(request.UUID, x) for x in os.listdir(userDir)])

        for f in loomsToProcess:
            if f.endswith('.loom'):
                loom = self.lfh.get_loom(loom_file_path=f)
                if loom is None:
                    continue
                file_meta = loom.get_file_metadata()
                if not file_meta['hasGlobalMeta']:
                    try:
                        loom.generate_meta_data()
                    except Exception as e:
                        print(e)

                try:
                    L1 = loom.get_global_attribute_by_name(name="SCopeTreeL1")
                    L2 = loom.get_global_attribute_by_name(name="SCopeTreeL2")
                    L3 = loom.get_global_attribute_by_name(name="SCopeTreeL3")
                except AttributeError:
                    L1 = 'Uncategorized'
                    L2 = L3 = ''
                my_looms.append(s_pb2.MyLoom(loomFilePath=f,
                                             loomDisplayName=os.path.splitext(os.path.basename(f))[0],
                                             cellMetaData=s_pb2.CellMetaData(annotations=loom.get_meta_data_by_key(key="annotations"),
                                                                             embeddings=loom.get_meta_data_by_key(key="embeddings"),
                                                                             clusterings=loom.get_meta_data_by_key(key="clusterings")),
                                             fileMetaData=file_meta,
                                             loomHeierarchy=s_pb2.LoomHeierarchy(L1=L1,
                                                                                 L2=L2,
                                                                                 L3=L3)
                                             )
                                )
        self.dfh.update_UUID_db()

        return s_pb2.MyLoomsReply(myLooms=my_looms)

    def getUUID(self, request, context):
        if SCope.app_mode:
            with open(os.path.join(self.dfh.get_config_dir(), 'Permanent_Session_IDs.txt'), 'r') as fh:
                newUUID = fh.readline().rstrip('\n')
        else:
            newUUID = str(uuid.uuid4())
        if newUUID not in self.dfh.get_current_UUIDs().keys():
            self.dfh.get_uuid_log().write("{0} :: {1} :: New UUID ({2}) assigned.\n".format(time.strftime('%Y-%m-%d__%H-%M-%S', time.localtime()), request.ip, newUUID))
            self.dfh.get_uuid_log().flush()
            self.dfh.get_current_UUIDs()[newUUID] = time.time()
        return s_pb2.UUIDReply(UUID=newUUID)

    def getRemainingUUIDTime(self, request, context):  # TODO: his function will be called a lot more often, we should reduce what it does.
        curUUIDSet = set(list(self.dfh.get_current_UUIDs().keys()))
        for uid in curUUIDSet:
            timeRemaining = int(dfh._UUID_TIMEOUT - (time.time() - self.dfh.get_current_UUIDs()[uid]))
            if timeRemaining < 0:
                print('Removing UUID: {0}'.format(uid))
                del(self.dfh.get_current_UUIDs()[uid])
                for i in ['Loom', 'GeneSet', 'LoomAUCellRankings']:
                    shutil.rmtree(os.path.join(self.dfh.get_data_dirs()[i]['path'], uid))
        uid = request.UUID
        if uid in self.dfh.get_current_UUIDs():
            startTime = self.dfh.get_current_UUIDs()[uid]
            timeRemaining = int(dfh._UUID_TIMEOUT - (time.time() - startTime))
            self.dfh.get_uuid_log().write("{0} :: {1} :: Old UUID ({2}) connected :: Time Remaining - {3}.\n".format(time.strftime('%Y-%m-%d__%H-%M-%S', time.localtime()), request.ip, uid, timeRemaining))
            self.dfh.get_uuid_log().flush()
        else:
            try:
                uuid.UUID(uid)
            except (KeyError, AttributeError):
                uid = str(uuid.uuid4())
            self.dfh.get_uuid_log().write("{0} :: {1} :: New UUID ({2}) assigned.\n".format(time.strftime('%Y-%m-%d__%H-%M-%S', time.localtime()), request.ip, uid))
            self.dfh.get_uuid_log().flush()
            self.dfh.get_current_UUIDs()[uid] = time.time()
            timeRemaining = int(dfh._UUID_TIMEOUT)

        self.dfh.active_session_check()
        if request.mouseEvents >= _MOUSE_EVENTS_THRESHOLD:
            self.dfh.reset_active_session_timeout(uid)

        sessionsLimitReached = False

        if len(self.dfh.get_active_sessions().keys()) >= _ACTIVE_SESSIONS_LIMIT and uid not in self.dfh.get_permanent_UUIDs() and uid not in self.dfh.get_active_sessions().keys():
            sessionsLimitReached = True

        if uid not in self.dfh.get_active_sessions().keys() and not sessionsLimitReached:
            self.dfh.reset_active_session_timeout(uid)
        return s_pb2.RemainingUUIDTimeReply(UUID=uid, timeRemaining=timeRemaining, sessionsLimitReached=sessionsLimitReached)

    def translateLassoSelection(self, request, context):
        src_loom = self.lfh.get_loom(loom_file_path=request.srcLoomFilePath)
        dest_loom = self.lfh.get_loom(loom_file_path=request.destLoomFilePath)
        src_cell_ids = [src_loom.get_cell_ids()[i] for i in request.cellIndices]
        src_fast_index = set(src_cell_ids)
        dest_mask = [x in src_fast_index for x in dest_loom.get_cell_ids()]
        dest_cell_indices = list(compress(range(len(dest_mask)), dest_mask))
        return s_pb2.TranslateLassoSelectionReply(cellIndices=dest_cell_indices)

    def getCellIDs(self, request, context):
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        cell_ids = loom.get_cell_ids()
        slctd_cell_ids = [cell_ids[i] for i in request.cellIndices]
        return s_pb2.CellIDsReply(cellIds=slctd_cell_ids)

    def deleteUserFile(self, request, context):
        basename = os.path.basename(request.filePath)
        finalPath = os.path.join(self.dfh.get_data_dirs()[request.fileType]['path'], request.UUID, basename)
        if os.path.isfile(finalPath) and (basename.endswith('.loom') or basename.endswith('.txt')):
            os.remove(finalPath)
            success = True
        else:
            success = False

        return s_pb2.DeleteUserFileReply(deletedSuccessfully=success)

    # Gene set enrichment
    #
    # Threaded makes it slower because of GIL
    #
    def doGeneSetEnrichment(self, request, context):
        gene_set_file_path = os.path.join(self.dfh.get_gene_sets_dir(), request.geneSetFilePath)
        loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
        gse = _gse.GeneSetEnrichment(scope=self,
                                method="AUCell",
                                loom=loom,
                                gene_set_file_path=gene_set_file_path,
                                annotation='')

        # Running AUCell...
        yield gse.update_state(step=-1, status_code=200, status_message="Running AUCell...", values=None)
        time.sleep(1)

        # Reading gene set...
        yield gse.update_state(step=0, status_code=200, status_message="Reading the gene set...", values=None)
        with open(gse.gene_set_file_path, 'r') as f:
            # Skip first line because it contains the name of the signature
            gs = GeneSignature('Gene Signature #1',
                               'FlyBase', [line.strip() for idx, line in enumerate(f) if idx > 0])
        time.sleep(1)

        if not gse.has_AUCell_rankings():
            # Creating the matrix as DataFrame...
            yield gse.update_state(step=1, status_code=200, status_message="Creating the matrix...", values=None)
            loom = self.lfh.get_loom(loom_file_path=request.loomFilePath)
            dgem = np.transpose(loom.get_connection()[:, :])
            ex_mtx = pd.DataFrame(data=dgem,
                                  index=loom.get_annotation_by_name("CellID"),
                                  columns=loom.get_genes())
            # Creating the rankings...
            start_time = time.time()
            yield gse.update_state(step=2.1, status_code=200, status_message="Creating the rankings...", values=None)
            rnk_mtx = create_rankings(ex_mtx=ex_mtx)
            # Saving the rankings...
            yield gse.update_state(step=2.2, status_code=200, status_message="Saving the rankings...", values=None)
            lp.create(gse.get_AUCell_ranking_filepath(), rnk_mtx.as_matrix(), {"CellID": loom.get_cell_ids()}, {"Gene": loom.get_genes()})
            print("Debug: %s seconds elapsed ---" % (time.time() - start_time))
        else:
            # Load the rankings...
            yield gse.update_state(step=2, status_code=200, status_message="Rankings exists: loading...", values=None)
            rnk_loom = self.lfh.get_loom_connection(gse.get_AUCell_ranking_filepath())
            rnk_mtx = pd.DataFrame(data=rnk_loom[:, :],
                                   index=rnk_loom.ra.CellID,
                                   columns=rnk_loom.ca.Gene)

        # Calculating AUCell enrichment...
        start_time = time.time()
        yield gse.update_state(step=3, status_code=200, status_message="Calculating AUCell enrichment...", values=None)
        aucs = enrichment(rnk_mtx, gs).loc[:, "AUC"].values

        print("Debug: %s seconds elapsed ---" % (time.time() - start_time))
        yield gse.update_state(step=4, status_code=200, status_message=gse.get_method() + " enrichment done!", values=aucs)

    def loomUploaded(self, request, content):
        uploadedLooms[request.UUID].add(request.filename)
        return s_pb2.LoomUploadedReply()


def serve(run_event, dev_env=False, port=50052, app_mode=False):
    SCope.dev_env = dev_env
    SCope.app_mode = app_mode
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    scope = SCope()
    s_pb2_grpc.add_MainServicer_to_server(scope, server)
    server.add_insecure_port('[::]:{0}'.format(port))
    # print('Starting GServer on port {0}...'.format(port))
    server.start()
    # Let the main process know that GServer has started.
    su.send_msg("GServer", "SIGSTART")

    while run_event.is_set():
        time.sleep(0.1)

    # Write UUIDs to file here
    scope.dfh.get_uuid_log().close()
    scope.dfh.update_UUID_db()
    server.stop(0)


if __name__ == '__main__':
    run_event = threading.Event()
    run_event.set()
    serve(run_event=run_event)
