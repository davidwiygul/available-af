# ml.py

import numpy as np
from typing import List, NamedTuple, Tuple


class Mask:
    """docstring"""
    def __init__(self, code: int, full_dim: int) -> None:
        """docstring"""
        assert 0 <= code < 2**full_dim
        self.full_dim = full_dim
        self.code = code
        self.array = None

    def __str__(self):
        return f"{self.code} of {2**self.full_dim}"

    def complement(self) -> 'Mask':
        """docstring"""
        return Mask(code = 2**self.full_dim - 1 - self.code,
		    full_dim = self.full_dim)

    def get_array(self) -> np.array:
        """docstring"""
        return np.array([(self.code & 2**bit) == 2**bit
			 for bit in range(self.full_dim)])

    def save_array(self) -> None:
        """docstring"""
        self.array = self.get_array()


class LinearPredictor:
    """docstring"""
    def __init__(self, column_rep: np.array = None) -> None:
        """docstring"""
        self.column_rep = column_rep

    def __str__(self) -> str:
        return str(self.column_rep)

    def predict(self, feature_rows: np.array) -> np.array:
        """docstring"""
        if self.column_rep is not None:
            return feature_rows@self.column_rep[1: ] + self.column_rep[0]

    def fit(self, data: 'LabeledData', mask: Mask = None) -> None:
        """docstring"""
        if mask is None:
            mask = Mask(code = 2**data.feature_dim - 1,
			full_dim = data.feature_dim) 
        else:
            assert mask.full_dim == data.feature_dim
        Xemb = np.concatenate((np.ones((data.size, 1)),
			       mask.get_array()*data.X),
			      axis=1)
        self.column_rep = np.linalg.lstsq(Xemb, data.y, rcond=-1)[0]
        marray = mask.get_array().reshape((data.feature_dim, 1))
        self.column_rep *= np.concatenate(([[1]], marray)) 

    def error(self, data: 'LabeledData') -> float:
        """docstring"""
        if self.column_rep is not None:
            return np.linalg.norm(np.linalg.norm(self.predict(data.X)-data.y,
					     axis=1)
		                  / np.linalg.norm(data.X, axis=1))


class LabeledData:
    """docstring"""
    def __init__(self, X: np.array, y: np.array) -> None:
        assert X.shape[0] == y.shape[0]
        self.X = X
        self.y = y
        self.size = y.shape[0]
        self.feature_dim = X.shape[1]

    def frac_split(self, frac: float) -> Tuple['LabeledData', 'LabeledData']:
        """docstring"""
        frac_length = int(frac*self.size)
        indices = np.random.permutation(self.size)
        indices_frac = indices[ : frac_length]
        indices_rest = indices[frac_length : ]
        return (LabeledData(self.X[indices_frac], self.y[indices_frac]),
		LabeledData(self.X[indices_rest], self.y[indices_rest]))

    def k_split(self, k: int) -> List[Mask]:
        """docstring"""
        assert 1 <= k <= self.size
        approx_fold_size = self.size // k
        indices = np.random.permutation(self.size)
        codes = [sum(2**index.item() for index in
                     indices[approx_fold_size*i : approx_fold_size*(i+1)])
		 for i in range(k)]
        for i in range(self.size % k):
            codes[i] += 2**indices[i+approx_fold_size*k].item()
        return [Mask(code=code, full_dim = self.size) for code in codes]

    def get_subset(self, mask: Mask) -> 'LabeledData':
        """docstring"""
        marray = mask.get_array()
        return LabeledData(self.X[marray], self.y[marray])


class Simulation(NamedTuple):
    """docstring"""
    target: LinearPredictor
    data: LabeledData 


def generate_target(feature_dim: int,
		    hot: int,
		    scale: float) -> LinearPredictor:
    """docstring"""
    active = np.random.choice(feature_dim, hot, replace=False)
    random = np.random.uniform(-scale, scale, hot)
    target_col = np.zeros(feature_dim+1)
    target_col[0] = np.random.uniform(-scale, scale)
    target_col[1:][active] = random
    return LinearPredictor(target_col.reshape((feature_dim+1, 1)))


def generate_X(feature_dim: int, cardinality: int, scale: float) -> np.array:
    """docstring"""
    return np.random.uniform(-scale, scale, size=((cardinality, feature_dim)))


def generate_label(target: LinearPredictor,
		   X: np.array,
		   scale: float) -> np.array:
    true = target.predict(X)
    error = np.random.normal(scale=scale, size=true.shape)
    return true+error


def simulate(feature_dim: int,
			hot: int,
			cardinality: int,
			target_scale: float,
			X_scale: float,
			error_scale: float) -> Simulation:
    """docstring"""
    target = generate_target(feature_dim, hot, target_scale)
    X = generate_X(feature_dim, cardinality, X_scale)
    return Simulation(target,
		      LabeledData(X, generate_label(target, X, error_scale)))
