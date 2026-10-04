import os

# Set offscreen platform for headless pytest execution
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
