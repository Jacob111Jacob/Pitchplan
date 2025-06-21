from flask import Flask

app = Flask(__name__)

@app.route('/')
def index():
    return "<h1>PitchPlan AI is live and working!</h1>"

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))  # 👈 This line is required by Render
    app.run(host='0.0.0.0', port=port)

