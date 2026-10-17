from sklearn.model_selection._split import _BaseKFold, indexable, _num_samples
from sklearn.utils.validation import _deprecate_positional_args
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error
from sklearn.svm import SVR
from xgboost import XGBRegressor
import pandas as pd
import numpy as np

# GroupTimeSeriesSplit is adapted from scikit-learn source under BSD-3-Clause.
# See ../../../licenses/scikit-learn-BSD-3-Clause.txt.
# https://github.com/getgaurav2/scikit-learn/blob/d4a3af5cc9da3a76f0266932644b884c99724c57/sklearn/model_selection/_split.py#L2243
class GroupTimeSeriesSplit(_BaseKFold):
    """Time Series cross-validator variant with non-overlapping groups.
    Provides train/test indices to split time series data samples
    that are observed at fixed time intervals according to a
    third-party provided group.
    In each split, test indices must be higher than before, and thus shuffling
    in cross validator is inappropriate.
    This cross-validation object is a variation of :class:`KFold`.
    In the kth split, it returns first k folds as train set and the
    (k+1)th fold as test set.
    The same group will not appear in two different folds (the number of
    distinct groups has to be at least equal to the number of folds).
    Note that unlike standard cross-validation methods, successive
    training sets are supersets of those that come before them.
    Read more in the :ref:`User Guide <cross_validation>`.
    Parameters
    ----------
    n_splits : int, default=5
        Number of splits. Must be at least 2.
    max_train_size : int, default=None
        Maximum size for a single training set.
    Examples
    --------
    >>> import numpy as np
    >>> from sklearn.model_selection import GroupTimeSeriesSplit
    >>> groups = np.array(['a', 'a', 'a', 'a', 'a', 'a',\
                           'b', 'b', 'b', 'b', 'b',\
                           'c', 'c', 'c', 'c',\
                           'd', 'd', 'd'])
    >>> gtss = GroupTimeSeriesSplit(n_splits=3)
    >>> for train_idx, test_idx in gtss.split(groups, groups=groups):
    ...     print("TRAIN:", train_idx, "TEST:", test_idx)
    ...     print("TRAIN GROUP:", groups[train_idx],\
                  "TEST GROUP:", groups[test_idx])
    TRAIN: [0, 1, 2, 3, 4, 5] TEST: [6, 7, 8, 9, 10]
    TRAIN GROUP: ['a' 'a' 'a' 'a' 'a' 'a']\
    TEST GROUP: ['b' 'b' 'b' 'b' 'b']
    TRAIN: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] TEST: [11, 12, 13, 14]
    TRAIN GROUP: ['a' 'a' 'a' 'a' 'a' 'a' 'b' 'b' 'b' 'b' 'b']\
    TEST GROUP: ['c' 'c' 'c' 'c']
    TRAIN: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]\
    TEST: [15, 16, 17]
    TRAIN GROUP: ['a' 'a' 'a' 'a' 'a' 'a' 'b' 'b' 'b' 'b' 'b' 'c' 'c' 'c' 'c']\
    TEST GROUP: ['d' 'd' 'd']
    """
    @_deprecate_positional_args
    def __init__(self,
                 n_splits=5,
                 *,
                 max_train_size=None
                 ):
        super().__init__(n_splits, shuffle=False, random_state=None)
        self.max_train_size = max_train_size

    def split(self, X, y=None, groups=None):
        """Generate indices to split data into training and test set.
        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            Training data, where n_samples is the number of samples
            and n_features is the number of features.
        y : array-like of shape (n_samples,)
            Always ignored, exists for compatibility.
        groups : array-like of shape (n_samples,)
            Group labels for the samples used while splitting the dataset into
            train/test set.
        Yields
        ------
        train : ndarray
            The training set indices for that split.
        test : ndarray
            The testing set indices for that split.
        """
        if groups is None:
            raise ValueError(
                "The 'groups' parameter should not be None")
        X, y, groups = indexable(X, y, groups)
        n_samples = _num_samples(X)
        n_splits = self.n_splits
        n_folds = n_splits + 1
        group_dict = {}
        u, ind = np.unique(groups, return_index=True)
        unique_groups = u[np.argsort(ind)]
        n_samples = _num_samples(X)
        n_groups = _num_samples(unique_groups)
        for idx in np.arange(n_samples):
            if (groups[idx] in group_dict):
                group_dict[groups[idx]].append(idx)
            else:
                group_dict[groups[idx]] = [idx]
        if n_folds > n_groups:
            raise ValueError(
                ("Cannot have number of folds={0} greater than"
                 " the number of groups={1}").format(n_folds,
                                                     n_groups))
        group_test_size = n_groups // n_folds
        group_test_starts = range(n_groups - n_splits * group_test_size,
                                  n_groups, group_test_size)
        for group_test_start in group_test_starts:
            train_array = []
            test_array = []
            for train_group_idx in unique_groups[:group_test_start]:
                train_array_tmp = group_dict[train_group_idx]
                train_array = np.sort(np.unique(
                                      np.concatenate((train_array,
                                                      train_array_tmp)),
                                      axis=None), axis=None)
            train_end = train_array.size
            if self.max_train_size and self.max_train_size < train_end:
                train_array = train_array[train_end -
                                          self.max_train_size:train_end]
            for test_group_idx in unique_groups[group_test_start:
                                                group_test_start +
                                                group_test_size]:
                test_array_tmp = group_dict[test_group_idx]
                test_array = np.sort(np.unique(
                                              np.concatenate((test_array,
                                                              test_array_tmp)),
                                     axis=None), axis=None)
            yield [int(i) for i in train_array], [int(i) for i in test_array]
            
# CV function
def apply_cv(X, y, regions):
    
    # Step 1: Set seed
    np.random.seed(0)

    # Step 2: Define models and parameter grids
    models = {
        'Random Forest': {
            'model': RandomForestRegressor(),
            'params': {
                'n_estimators': [50, 100],
                'max_depth': [None, 10]
            }
        },
        'XGBoost': {
            'model': XGBRegressor(),
            'params': {
                'n_estimators': [50, 100],
                'max_depth': [3, 6],
                'learning_rate': [0.01, 0.1]
            }
        },
        'SVR': {
            'model': SVR(),
            'params': {
                'kernel': ['linear', 'rbf'],
                'C': [1, 10]
            }
        },
        'Linear': {
            'model': LinearRegression(),
            'params': {}
        }
    }

    # Step 3: TimeSeriesSplit cross-validation
    tscv = GroupTimeSeriesSplit(n_splits=5)

    # Step 4 & 5: Hyperparameter tuning and evaluation
    results = {}
    gs_fits = {}
    for model_name, model_config in models.items():
        gs = GridSearchCV(model_config['model'], model_config['params'], cv=tscv, scoring='neg_mean_squared_error', n_jobs=-1)
        gs.fit(X, y, groups=regions)
        results[model_name] = {
            'best_params': gs.best_params_,
            'best_score': -gs.best_score_,
            'r-squared': 1 - (-gs.best_score_) / np.mean((y - np.mean(y))**2)
        }
        gs_fits[model_name] = gs

    return results, gs_fits

# Run CV
def run_cv(data_model):# Obtain cross-validation results
    cv_results = {}
    for crop, data_arrays in data_model.items():
        print(f'{crop} models...')
        X = data_arrays[4]
        y = data_arrays[1]
        regions = data_arrays[2]
        cv_results[crop] = apply_cv(X, y, regions)
        
    return cv_results

# Get performance tables
def get_performances(cv_results):
    # Collect performances
    performances = {}
    for crop, results in cv_results.items():
        performance_table = pd.DataFrame({
            "Model": [model_name for model_name in results[0].keys()],
            "MSE": np.round([model['best_score'] for _,model in results[0].items()], 3), 
            "R-squared": np.round([model['r-squared'] for _,model in results[0].items()], 3)
        })
        performance_table['Rank'] = performance_table['MSE'].argsort() + 1
        performances[crop] = performance_table
    
    return performances

# Estimate final model
def estimate_final_model(data_model, performances, cv_results):
    final_models = {}
    for crop in data_model.keys():
        
        # Get data
        X = data_model[crop][4]
        y = data_model[crop][1]
        regions = data_model[crop][2]
        
        # Select final model
        model_name = performances[crop].Model[performances[crop].Rank == 1].item()
        final_model = cv_results[crop][1][model_name].best_estimator_
        
        # Train model
        print(f'Train final {crop} model ({model_name})...')
        final_model.fit(X, y)
        final_models[crop] = final_model
    print("Model training complete.")
    
    return final_models

# Predict trends
def predict_trends(dfs, trend_models):
    
    dfs_trend_predictions = {}
    
    # Iterate over crops and respective data
    for crop, data in dfs.items():
        
        # Subset data
        data_model = data[['Province', 'year']].copy()
        data_model['year2'] = data_model['year']**2
        data_model['year3'] = data_model['year']**3
        
        # Get unique provinces
        unique_provinces = np.unique(data['Province'])
        
        # Init data
        data_list = []
        
        # Iterate over provinces and get predicted trend
        for province in unique_provinces:
            
            # Subset data
            data_province = data_model[data_model['Province'] == province].copy()
            model = trend_models[crop][province]
            data_province['trend_prediction'] = model.predict(data_province[['year', 'year2', 'year3']])
            
            # Store
            data_list.append(data_province)
            
        # Combine province data
        dfs_trend_predictions[crop] = pd.concat(data_list).drop(columns=['year2', 'year3'])        
    
    return dfs_trend_predictions
        
# Predict models
def predict_models(data_model_predict, dfs_trend_predictions, final_models):
    
    dfs_predictions = {}
    
    # Iterate over crops
    for crop, model in final_models.items():
        
        # Get data
        data = data_model_predict[crop][0].copy()
        X = data_model_predict[crop][3]
        
        # Make predictions
        y_pred = model.predict(X)
        data['prediction_detrended'] = y_pred
        
        # Add trend
        data_merged = data.merge(dfs_trend_predictions[crop], on=['Province', 'year'], how='left')
        data_merged['prediction'] = data_merged['prediction_detrended'] + data_merged['trend_prediction']
        
        dfs_predictions[crop] = data_merged    
        
    return dfs_predictions

