# model_select.py
"""Model selection DAG and supporting functions."""

from datetime import datetime
from datetime import timedelta

from airflow import DAG
from airflow.operators.python_operator import PythonOperator

import ml
from riak_python_object_bucket import RiakPythonObjectBucket

# constants at user's disposal
FEATURE_DIM = 4
CARDINALITY = 100
TARGET_SCALE = 10
X_SCALE = 1
ERROR_SCALE = 4
K = 5


def simulate() -> None:
    """Creates and stores ml.Simulation along with test/train split."""
    simulation = ml.simulate(feature_dim=FEATURE_DIM,
                             cardinality=CARDINALITY,
                             target_scale=TARGET_SCALE,
                             X_scale=X_SCALE,
                             error_scale=ERROR_SCALE)
    data = RiakPythonObjectBucket('data')
    data.put('target', simulation.target)
    test_data, training_data = simulation.data.frac_split(.1)
    data.put('train', training_data)
    data.put('test', test_data)


def fold_split() -> None:
    """Creates and stores cross validation folds."""
    data = RiakPythonObjectBucket('data')
    folds = RiakPythonObjectBucket('folds')
    for index, fold in enumerate(data.get('train').k_split(K)):
        folds.put(str(index), fold)


def train_model(model_index: int, fold_index: int) -> None:
    """Trains given model on complement of given fold and stores predictor."""
    model = ml.Mask(code=model_index, full_dim=FEATURE_DIM)
    fold = RiakPythonObjectBucket('folds').get(str(fold_index))
    train = RiakPythonObjectBucket('data').get('train')
    predictors = RiakPythonObjectBucket('predictors')
    predictor = ml.LinearPredictor()
    predictor.fit(data=train.get_subset(fold.complement()), mask=model)
    predictors.put(f"model {model_index}, fold {fold_index}", predictor)


def evaluate_error(model_index: int, fold_index: int) -> None:
    """Evaluates and stores error of given trained model on given fold."""
    fold = RiakPythonObjectBucket('folds').get(str(fold_index))
    train = RiakPythonObjectBucket('data').get('train')
    predictors = RiakPythonObjectBucket('predictors')
    predictor = predictors.get(f"model {model_index}, fold {fold_index}")
    errors = RiakPythonObjectBucket('errors')
    error = predictor.error(train.get_subset(fold))
    errors.put(f"model {model_index}, fold {fold_index}", error)


def average_error(model_index: int) -> None:
    """Calculates and stores fold average of error made by given model."""
    errors = RiakPythonObjectBucket('errors')
    error_averages = RiakPythonObjectBucket('error_averages')
    avg_error = sum(errors.get(f"model {model_index}, fold {fold_index}")
                    for fold_index in range(K)) / K
    error_averages.put(f"model {model_index}", avg_error)


def minimize() -> None:
    """Finds and stores model minimizing average error over all folds."""
    error_averages = RiakPythonObjectBucket('error_averages')
    min_model_index = 0
    for model_index in range(2**FEATURE_DIM):
        current_min_error = error_averages.get(f"model {min_model_index}")
        current_error = error_averages.get(f"model {model_index}")
        if current_error < current_min_error:
            min_model_index = model_index
    report = RiakPythonObjectBucket('report')
    report.put('model', ml.Mask(code=min_model_index, full_dim=FEATURE_DIM))


def train_min() -> None:
    """Trains minimizing model on entire training set and stores predictor."""
    report = RiakPythonObjectBucket('report')
    train = RiakPythonObjectBucket('data').get('train')
    predictor = ml.LinearPredictor()
    predictor.fit(data=train, mask=report.get('model'))
    report.put('predictor', predictor)


def report_error() -> None:
    """Computes and stores error made by trained minimizer on test set."""
    report = RiakPythonObjectBucket('report')
    predictor = report.get('predictor')
    test = RiakPythonObjectBucket('data').get('test')
    error = predictor.error(test)
    report.put('test_error', error)


default_args = {'owner': 'airflow',
                'depends_on_past': False,
                'start_date': datetime(2020, 3, 22),
                'email_on_failure': False,
                'email_on_retry': False,
                'retries': 10,
                'retry_delay': timedelta(seconds=30)}

dag = DAG('model_select',
          default_args=default_args,
          schedule_interval=timedelta(days=1))

task_sim = PythonOperator(task_id='simulate_data',
                          python_callable=simulate,
                          dag=dag)

task_ff = PythonOperator(task_id='form_folds',
                         python_callable=fold_split,
                         dag=dag)

task_sim >> task_ff

task_min = PythonOperator(task_id='minimize_error',
                          python_callable=minimize,
                          dag=dag)

task_train_min = PythonOperator(task_id='train_minimizing_model',
                                python_callable=train_min,
                                dag=dag)

task_report_error = PythonOperator(task_id='report_error',
                                   python_callable=report_error,
                                   dag=dag)

task_min >> task_train_min >> task_report_error

for model_index in range(2**FEATURE_DIM):
    avg_err_task_id = f"evaluate_average_error_of_M_{model_index}"
    task_avg_err = PythonOperator(task_id=avg_err_task_id,
                                  python_callable=average_error,
                                  op_args=[model_index],
                                  dag=dag)

    for fold_index in range(K):
        train_task_id = f"train_M_{model_index}_off_F_{fold_index}"
        task_train = PythonOperator(task_id=train_task_id,
                                    python_callable=train_model,
                                    op_args=[model_index, fold_index],
                                    dag=dag)

        error_task_id = f"evaluate_error_of_M_{model_index}_on_F_{fold_index}"
        task_err = PythonOperator(task_id=error_task_id,
                                  python_callable=evaluate_error,
                                  op_args=[model_index, fold_index],
                                  dag=dag)

        task_ff >> task_train >> task_err >> task_avg_err >> task_min
