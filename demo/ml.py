# ml.py
"""Library for data splitting and linear regression with feature selection."""

from typing import List, NamedTuple, Tuple
import numpy as np


class Mask:
    """Specification of a subset of an ordered set.

    A subset of {1, 2, ..., n} can be specified by an n-bit binary number
    whose jth bit indicates the inclusion of j in the subset.

    Attributes:
        full_dim: A nonnegative integer signifying the cardinality of the full
                  set of which Mask designates a subset.
        code: A nonnegative integer having binary representation as above.
        array: If initialized, a boolean (full_dim, ) np.array expressing the
               binary representation of the code attribute; otherwise None.
    """

    def __init__(self, code: int, full_dim: int) -> None:
        """Initializes Mask with given full_dim and code."""
        assert 0 <= code < 2**full_dim
        self.full_dim = full_dim
        self.code = code
        self.array = None

    def __str__(self) -> str:
        """Returns a string representation of Mask."""
        return f"{self.code} of {2**self.full_dim}"

    def complement(self) -> 'Mask':
        """Returns the Mask representing the set-theoretic complement of the
           subset represented by this Mask."""
        return Mask(code=2**self.full_dim - 1 - self.code,
                    full_dim=self.full_dim)

    def get_array(self) -> np.array:
        """Returns the binary rep of Mask as a boolean (full_dim, ) np.array."""
        return np.array([(self.code & 2**bit) == 2**bit
                         for bit in range(self.full_dim)])

    def save_array(self) -> None:
        """Stores the binary representation of code as the array attribute."""
        self.array = self.get_array()


class LinearPredictor:
    """A linear regression model.

    Attributes:
        column_rep: When initialized, a float (d+1, 1) np.array representing
                    a scalar-valued linear predictor on d features,
                    with bias entry [0, 0].
    """

    def __init__(self, column_rep: np.array = None) -> None:
        """Initializes LinearPredictor with column_rep, if given."""
        self.column_rep = column_rep

    def __str__(self) -> str:
        """Returns a string representation of LinearPredictor."""
        return str(self.column_rep)

    def predict(self, feature_rows: np.array) -> np.array:
        """Assuming column_rep has been set to a (d+1, 1) np.array,
           returns a float (N, 1) np.array whose entries are the predictions
           corresponding to the given (N, d) data np.array."""
        if self.column_rep is not None:
            return feature_rows@self.column_rep[1:] + self.column_rep[0]
        return None

    def fit(self, data: 'LabeledData', mask: Mask = None) -> None:
        """Sets column_rep to (1, d+1) least-squares predictor for given
           LabeledData (whose inputs have d features)
           and using only those features specified by given Mask."""
        if mask is None:
            mask = Mask(code=2**data.feature_dim - 1,
                        full_dim=data.feature_dim)
        else:
            assert mask.full_dim == data.feature_dim
        Xemb = np.concatenate((np.ones((data.size, 1)),
                               mask.get_array() * data.X),
                              axis=1)
        self.column_rep = np.linalg.lstsq(Xemb, data.y, rcond=-1)[0]
        marray = mask.get_array().reshape((data.feature_dim, 1))
        self.column_rep *= np.concatenate(([[1]], marray))

    def error(self, data: 'LabeledData') -> float:
        """Assuming column_rep has been set, returns error LinearPredictor
           makes on given LabeledData, normalized by size of input."""
        if self.column_rep is not None:
            return np.linalg.norm(np.linalg.norm(self.predict(data.X) - data.y,
                                                 axis=1)
                                  / np.linalg.norm(data.X, axis=1))
        return None


class LabeledData:
    """Collection of feature vectors along with corresponding labels.

    Attributes:
        X: A float (N, d) np.array representing N feature vectors.
        y: A float (N, 1) np.array representing N labels corresponding to X.
        size: An int (N), the number of feature vectors (and also labels).
        feature_dim: An int (d), the number of features in each input datum.
    """

    def __init__(self, X: np.array, y: np.array) -> None:
        """Initializes all attributes, given X and y."""
        assert X.shape[0] == y.shape[0]
        self.X = X
        self.y = y
        self.size = y.shape[0]
        self.feature_dim = X.shape[1]

    def frac_split(self, frac: float) -> Tuple['LabeledData', 'LabeledData']:
        """Returns tuple of LabeledData randomly partitioning this LabeledData
           so that the first LabeledData has size (approximately) given fraction
           of this LabeledData's size."""
        frac_length = int(frac * self.size)
        indices = np.random.permutation(self.size)
        indices_frac = indices[: frac_length]
        indices_rest = indices[frac_length:]
        return (LabeledData(self.X[indices_frac], self.y[indices_frac]),
                LabeledData(self.X[indices_rest], self.y[indices_rest]))

    def k_split(self, k: int) -> List[Mask]:
        """Given a positive int k,
           returns a list of k random Masks partitioning LabeledData."""
        assert 1 <= k <= self.size
        approx_fold_size = self.size // k
        indices = np.random.permutation(self.size)
        codes = [sum(2**index.item() for index in
                     indices[approx_fold_size * i: approx_fold_size * (i + 1)])
                 for i in range(k)]
        for i in range(self.size % k):
            codes[i] += 2**indices[i + approx_fold_size * k].item()
        return [Mask(code=code, full_dim=self.size) for code in codes]

    def get_subset(self, mask: Mask) -> 'LabeledData':
        """Returns LabeledData corresponding to the subset of this LabeledData
           designated by the given Mask."""
        marray = mask.get_array()
        return LabeledData(self.X[marray], self.y[marray])


class Simulation(NamedTuple):
    """A linear predictor and simulated data."""
    target: LinearPredictor
    data: LabeledData


def generate_target(feature_dim: int,
                    hot: int,
                    scale: float) -> LinearPredictor:
    """Returns a randomly generated LinearPredictor defined on a given number
       of features, sensitive to only a given number of them, and having
       entries within a given scale."""
    active = np.random.choice(feature_dim, hot, replace=False)
    random = np.random.uniform(-scale, scale, hot)
    target_col = np.zeros(feature_dim + 1)
    target_col[0] = np.random.uniform(-scale, scale)
    target_col[1:][active] = random
    return LinearPredictor(target_col.reshape((feature_dim + 1, 1)))


def generate_X(feature_dim: int, cardinality: int, scale: float) -> np.array:
    """Generates cardinality feature vectors with feature_dim features,
       each with absolute value bounded by given scale."""
    return np.random.uniform(-scale, scale, size=((cardinality, feature_dim)))


def generate_label(target: LinearPredictor,
                   X: np.array,
                   scale: float) -> np.array:
    """Generates labels predicted by given LinearPredictor target for given
       feature vectors X subject to random error controlled by given scale."""
    true = target.predict(X)
    error = np.random.normal(scale=scale, size=true.shape)
    return true + error


def simulate(feature_dim: int,
             cardinality: int,
             target_scale: float,
             X_scale: float,
             error_scale: float) -> Simulation:
    """Returns a Simulation with given number of features, data cardinality,
       scale of LinearPredictor, scale of data, and scale of error in labels."""
    hot = np.random.choice(feature_dim + 1)
    target = generate_target(feature_dim, hot, target_scale)
    X = generate_X(feature_dim, cardinality, X_scale)
    return Simulation(target,
                      LabeledData(X, generate_label(target, X, error_scale)))
