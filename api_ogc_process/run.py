from flask_ogc_api_processes import create_app

app = create_app()

if __name__ == '__main__':
    # Start the application in development mode

    app.run(debug=False)
