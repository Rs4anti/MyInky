"""Run the local development server."""

from inkdisplay.app import create_app

app = create_app()


if __name__ == "__main__":
    scheduler = app.extensions["inkdisplay.scheduler"]
    scheduler.start()
    try:
        app.run(
            host=str(app.config["HOST"]),
            port=int(app.config["PORT"]),
            debug=False,
            use_reloader=False,
        )
    finally:
        try:
            scheduler.shutdown()
        finally:
            app.extensions["inkdisplay.display"].close()
