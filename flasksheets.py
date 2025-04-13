from flask import Flask
import os

app = Flask(__name__)

@app.route('/env')
def get_env():
    sheet_range = os.environ.get('SHEET_RANGE')
    return f"SHEET_RANGE: {sheet_range}"

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
