from agentkit.runtime.tools._vector_math import cosine_similarity


def test_identical_vectors_score_one():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_orthogonal_vectors_score_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_zero_vector_scores_zero_not_nan():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
