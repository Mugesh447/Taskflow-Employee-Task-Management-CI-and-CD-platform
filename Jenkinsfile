pipeline {
    agent any

    environment {
        IMAGE = "taskflow:${BUILD_NUMBER}"
    }

    stages {
        stage('Test') {
            steps {
                sh 'python -m pip install -r backend/requirements.txt'
                sh 'python -m compileall -q backend'
                sh 'python -m unittest discover -s tests -v'
            }
        }
        stage('Build image') {
            steps {
                sh 'docker build -t ${IMAGE} .'
            }
        }
        stage('Deploy to Kubernetes') {
            when {
                expression { return env.KUBE_CONTEXT?.trim() }
            }
            steps {
                sh 'kubectl config use-context ${KUBE_CONTEXT}'
                sh 'kubectl set image deployment/taskflow taskflow=${IMAGE} --record'
                sh 'kubectl rollout status deployment/taskflow --timeout=120s'
            }
        }
    }
}
