# model_select.py

from airflow import DAG
from airflow.operators.python_operator import PythonOperator

from datetime import datetime
from datetime import timedelta

import ml
from riak_python_object_bucket import RiakPythonObjectBucket


feature_dim = 5
hot = 3
cardinality = 100
target_scale = 10
X_scale = 1
error_scale = 4
k = 5


def simulate() -> None:
    simulation = ml.simulate(feature_dim = feature_dim,
		             hot = hot,
		             cardinality = cardinality,
		             target_scale = target_scale,
		             X_scale = X_scale,
		             error_scale = error_scale)
    data = RiakPythonObjectBucket('data')
    data.put('target', simulation.target)
    test_data, training_data = simulation.data.frac_split(.1)
    data.put('train', training_data)
    data.put('test', test_data)

def fold() -> None:
    data = RiakPythonObjectBucket('data')
    folds = RiakPythonObjectBucket('folds')
    for index, fold in enumerate(data.get('train').k_split(k)):
        folds.put(str(index), fold)

def train(model_index: int, fold_index: int) -> None:
    model = ml.Mask(code=model_index, full_dim=feature_dim)
    fold = RiakPythonObjectBucket('folds').get(str(fold_index))
    train = RiakPythonObjectBucket('data').get('train')
    predictors = RiakPythonObjectBucket('predictors')
    predictor = ml.LinearPredictor()
    predictor.fit(data = train.get_subset(fold.complement()), mask = model)
    predictors.put(f"model {model_index}, fold {fold_index}", predictor)

def error(model_index: int, fold_index: int) -> None:
    model = ml.Mask(code=model_index, full_dim=feature_dim)
    fold = RiakPythonObjectBucket('folds').get(str(fold_index))
    train = RiakPythonObjectBucket('data').get('train')
    predictors = RiakPythonObjectBucket('predictors')
    predictor = predictors.get(f"model {model_index}, fold {fold_index}")
    errors = RiakPythonObjectBucket('errors')
    error = predictor.error(train.get_subset(fold))
    errors.put(f"model {model_index}, fold {fold_index}", error)

def average_error(model_index: int) -> None:
    errors = RiakPythonObjectBucket('errors')
    error_averages = RiakPythonObjectBucket('error_averages')
    avg_error = sum(errors.get(f"model {model_index}, fold {fold_index}")
                    for fold_index in range(k))/k
    error_averages.put(f"model {model_index}", avg_error)

def minimize() -> None:
    error_averages = RiakPythonObjectBucket('error_averages')
    min_model_index = 0
    for model_index in range(2**feature_dim):
        current_min_error = error_averages.get(f"model {min_model_index}")
        current_error = error_averages.get(f"model {model_index}")
        if current_error < current_min_error:
            min_model_index = model_index
    report = RiakPythonObjectBucket('report')
    report.put('model', ml.Mask(code=min_model_index, full_dim=feature_dim))

def train_min() -> None:
    report = RiakPythonObjectBucket('report')
    train = RiakPythonObjectBucket('data').get('train')
    predictor = ml.LinearPredictor()
    predictor.fit(data=train, mask=report.get('model'))
    report.put('predictor', predictor)

def report_error() -> None:
    report = RiakPythonObjectBucket('report')
    predictor = report.get('predictor')
    test = RiakPythonObjectBucket('data').get('test')
    error = predictor.error(test)
    report.put('test_error', error)
   

default_args={'owner': 'airflow',
              'depends_on_past': False,
              'start_date': datetime(2020, 3, 2),
              'email_on_failure': False,
              'email_on_retry': False,
              'retries': 10,
              'retry_delay': timedelta(seconds=30)}

dag=DAG('model_select',
        default_args=default_args,
        schedule_interval=timedelta(days=1))

task_sim = PythonOperator(task_id='simulate_data',
                          python_callable=simulate,
                          dag=dag)

task_ff = PythonOperator(task_id='form_folds',
                         python_callable=fold,
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

for model_index in range(2**feature_dim):
    avg_err_task_id = f"evaluate_average_error_of_M_{model_index}"
    task_avg_err = PythonOperator(task_id=avg_err_task_id,
                                        python_callable=average_error,
                                        op_args=[model_index],
                                        dag=dag)

    for fold_index in range(k):
        train_task_id = f"train_M_{model_index}_off_F_{fold_index}"
        task_train = PythonOperator(task_id=train_task_id,
                                    python_callable=train,
                                    op_args=[model_index, fold_index],
                                    dag=dag)
        
        error_task_id = f"evaluate_error_of_M_{model_index}_on_F_{fold_index}"
        task_err = PythonOperator(task_id=error_task_id,
                                    python_callable=error,
                                    op_args=[model_index, fold_index],
                                    dag=dag)
        
        task_ff >> task_train >> task_err >> task_avg_err >> task_min

"""

minimizing_model = models.get(str(minimizing_model_index))
best_predictor = ml.LinearPredictor()
best_predictor.fit(data = data.get('train'), mask = minimizing_model)
test_error = best_predictor.error(data.get('test'))
""" 

"""
print("target:")
print(data.get('target'))
print("test error:")
print(test_error)
print("hypothesis:")
print(best_predictor)
print("model:")
print(minimizing_model)
print(minimizing_model.get_array())
"""

