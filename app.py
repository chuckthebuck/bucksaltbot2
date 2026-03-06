from flask import Flask
from celery_init import celery_init_app
from redis_init import redis_url, REDIS_KEY_PREFIX
from blueprint import assets_blueprint

def create_app() -> Flask:
    app = Flask(__name__,
        static_url_path="/",
        static_folder="public",
        template_folder="templates",
    )

    app.register_blueprint(assets_blueprint)
    app.config.from_mapping(
        CELERY=dict(
            broker_url=redis_url,
            result_backend=redis_url,
            retry_policy={
                'max_retries': 10 * 1000, # absurdly high
                'interval_start': 2,
                'interval_step': 2
            },
            task_default_queue=REDIS_KEY_PREFIX + '-celery-queue',
            task_ignore_result=True,
        ),
    )
    app.config.from_prefixed_env()
    celery_init_app(app)
    return app

flask_app = create_app()

celery = flask_app.extensions['celery']