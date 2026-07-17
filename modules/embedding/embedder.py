from langchain_huggingface import HuggingFaceEmbeddings
from sklearn.feature_extraction.text import TfidfVectorizer
from modules.embedding import proprecessor
import numpy as np

tfif_vectorizer =  TfidfVectorizer(
        preprocessor=None, 
        stop_words='english',
        analyzer='word',
        lowercase=False,
        use_idf=True,
        smooth_idf=True,
        sublinear_tf=True,
        norm=None
    )

sentence_transformer = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")

def getSparseEmbedder():
    return tfif_vectorizer

def getDenseEmbedder():
    return sentence_transformer

def generate_sparse_embedding(query: str):
    """Generates a sparse embedding for the given query using SparseEmbedder."""
    print("INSIDE generate_sparse_embedding")
    normalized_query = proprecessor.normalize_text(query)
    vec = getSparseEmbedder().fit_transform([normalized_query])
    vec_array = vec[0].toarray().squeeze()
    indices = np.atleast_1d(vec_array).nonzero()[0].tolist()
    values = vec_array[indices].tolist()
    return {"indices": indices, "values": values}
