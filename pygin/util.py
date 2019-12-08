import networkx as nx
import numpy as np
import scipy.sparse as sp
import random
import torch
from sklearn.model_selection import StratifiedKFold

class S2VGraph(object):
    def __init__(self, g, label, node_tags=None, node_features=None):
        '''
            g: a networkx graph
            label: an integer graph label
            node_tags: a list of integer node tags
            node_features: a torch float tensor, one-hot representation of the tag that is used as input to neural nets
            edge_mat: a torch long tensor, contain edge list, will be used to create torch sparse tensor
            neighbors: list of neighbors (without self-loop)
        '''
        self.label = label
        self.g = g
        self.node_tags = node_tags
        self.neighbors = []
        self.node_features = 0
        self.edge_mat = 0
        self.max_neighbor = 0


def encode_onehot(labels):
    classes = set(labels)
    classes_dict = {c: np.identity(len(classes))[i, :] for i, c in
                    enumerate(classes)}
    labels_onehot = np.array(list(map(classes_dict.get, labels)),
                             dtype=np.int32)
    return labels_onehot


def load_data(dataset, degree_as_tag):
    """Load Twitter dataset"""
    print('Loading {} dataset...'.format(dataset))

    path="../data/" + dataset + "/"
    idx_features_labels = np.genfromtxt("{}{}.features_small".format(path, dataset),
                                        delimiter=',',
                                        dtype=np.dtype(str))

    # delete rows and columns that are not required
    idx_features_labels = np.delete(idx_features_labels, np.s_[0], axis=0)
    idx_features_labels = np.delete(idx_features_labels, np.s_[1:3], axis=1)

    features = sp.csr_matrix(idx_features_labels[:, 2:], dtype=np.float32)
    features = normalize_features(features)

    labels = encode_onehot(idx_features_labels[:, 1])

    # build graph
    idx = np.array(idx_features_labels[:, 0], dtype=np.int32)
    idx_map = {j: i for i, j in enumerate(idx)}
    edges_unordered = np.genfromtxt("{}{}.graph_small".format(path, dataset),
                                    delimiter=',',
                                    dtype=np.int32)

    # delete rows that we don't need
    edges_unordered = np.delete(edges_unordered, np.s_[0], axis=0)
    x = list(map(idx_map.get, edges_unordered.flatten()))
    y = [0 if i is None else i for i in x]
    edges = np.array(y, dtype=np.int32)
    edges = edges.reshape(edges_unordered.shape)
    print("edges shape:", edges.shape)

    adj = sp.coo_matrix((np.ones(edges.shape[0]), (edges[:, 0], edges[:, 1])),
                        shape=(labels.shape[0], labels.shape[0]),
                        dtype=np.float32)

    # build symmetric adjacency matrix
    adj = adj + adj.T.multiply(adj.T > adj) - adj.multiply(adj.T > adj)

    g_list = []
    label_dict = {}
    feat_dict = {}

    """
    n_g = int(f.readline().strip())
    for i in range(n_g):
        row = f.readline().strip().split()
        n, l = [int(w) for w in row]
        if not l in label_dict:
            mapped = len(label_dict)
            label_dict[l] = mapped
        g = nx.Graph()
        node_tags = []
        node_features = []
        n_edges = 0
        for j in range(n):
            g.add_node(j)
    """

    l = 1 #  label 
    if not l in label_dict:
        mapped = len(label_dict)
        label_dict[l] = mapped

    g = nx.Graph()
    node_tags = []
    node_features = []
    n_edges = 0

    n = len(idx_features_labels) 
    # Each Node
    for j in range(n):
        row = list(idx_features_labels[j])
        g.add_node(row[0])

        feat = row[1]
        if not feat in feat_dict:
            mapped = len(feat_dict)
            feat_dict[feat] = mapped
        node_tags.append(feat_dict[feat])

        attr = row[2:]
        node_features.append(attr)

        node_idx = idx_map[row[0].astype(np.int32)]
        dsts = list(adj[node_idx].nonzero()[1])
        n_edges += adj[node_idx].count_nonzero()

        # Each Edge
        for dst in dsts:
            g.add_edge(node_idx, dst)

    if node_features != []:
        node_features = np.stack(node_features)
        node_feature_flag = True
    else:
        node_features = None
        node_feature_flag = False

    g_list.append(S2VGraph(g, l, node_tags))

    #add labels and edge_mat       
    for g in g_list:
        g.neighbors = [[] for i in range(len(g.g))]
        for i, j in g.g.edges():
            g.neighbors[i].append(j)
            g.neighbors[j].append(i)
        degree_list = []
        for i in range(len(g.g)):
            g.neighbors[i] = g.neighbors[i]
            degree_list.append(len(g.neighbors[i]))
        g.max_neighbor = max(degree_list)

        g.label = label_dict[g.label]

        edges = [list(pair) for pair in g.g.edges()]
        edges.extend([[i, j] for j, i in edges])

        deg_list = list(dict(g.g.degree(range(len(g.g)))).values())
        g.edge_mat = torch.LongTensor(edges).transpose(0,1)

    if degree_as_tag:
        for g in g_list:
            g.node_tags = list(dict(g.g.degree).values())

    #Extracting unique tag labels   
    tagset = set([])
    for g in g_list:
        tagset = tagset.union(set(g.node_tags))

    tagset = list(tagset)
    tag2index = {tagset[i]:i for i in range(len(tagset))}

    for g in g_list:
        g.node_features = torch.zeros(len(g.node_tags), len(tagset))
        g.node_features[range(len(g.node_tags)), [tag2index[tag] for tag in g.node_tags]] = 1

    print('# classes: %d' % len(label_dict))
    print('# maximum node tag: %d' % len(tagset))
    print("# data: %d" % len(g_list))

    return g_list, len(label_dict)

def separate_data(graph_list, seed, fold_idx):
    assert 0 <= fold_idx and fold_idx < 10, "fold_idx must be from 0 to 9."
    skf = StratifiedKFold(n_splits=10, shuffle = True, random_state = seed)

    labels = [graph.label for graph in graph_list]
    idx_list = []
    for idx in skf.split(np.zeros(len(labels)), labels):
        idx_list.append(idx)
    train_idx, test_idx = idx_list[fold_idx]

    train_graph_list = [graph_list[i] for i in train_idx]
    test_graph_list = [graph_list[i] for i in test_idx]

    return train_graph_list, test_graph_list


def normalize_adj(mx):
    """Row-normalize sparse matrix"""
    rowsum = np.array(mx.sum(1))
    r_inv_sqrt = np.power(rowsum, -0.5).flatten()
    r_inv_sqrt[np.isinf(r_inv_sqrt)] = 0.
    r_mat_inv_sqrt = sp.diags(r_inv_sqrt)
    return mx.dot(r_mat_inv_sqrt).transpose().dot(r_mat_inv_sqrt)


def normalize_features(mx):
    """Row-normalize sparse matrix"""
    rowsum = np.array(mx.sum(1))
    r_inv = np.power(rowsum, -1).flatten()
    r_inv[np.isinf(r_inv)] = 0.
    r_mat_inv = sp.diags(r_inv)
    mx = r_mat_inv.dot(mx)
    return mx
