from sklearn.linear_model import LogisticRegression
import pickle
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def save_model(model, model_name):
    with (BASE_DIR / model_name).open("wb") as model_file:
        pickle.dump(model, model_file)

# --- 1. DIABETES MODEL ---
# Features: [Pregnancies, Glucose, BloodPressure, BMI, Age]
diabetes_X = [[0, 80, 70, 22.0, 25], [2, 120, 75, 28.0, 35], [5, 160, 80, 35.0, 50], [1, 100, 60, 20.0, 22]]
diabetes_y = [0, 0, 1, 0] # 0 = No Diabetes, 1 = Diabetes

diabetes_model = LogisticRegression()
diabetes_model.fit(diabetes_X, diabetes_y)
save_model(diabetes_model, "diabetes_model.pkl")
print("✅ Diabetes Model Saved!")

# --- 2. HEART DISEASE MODEL ---
# Features: [Age, Cholesterol, Max Heart Rate, Oldpeak]
heart_X = [[25, 180, 150, 0.5], [40, 220, 140, 1.0], [60, 260, 120, 2.5], [30, 190, 160, 0.0]]
heart_y = [0, 0, 1, 0] # 0 = Healthy, 1 = Heart Disease

heart_model = LogisticRegression()
heart_model.fit(heart_X, heart_y)
save_model(heart_model, "heart_model.pkl")
print("✅ Heart Disease Model Saved!")

# --- 3. LIVER DISEASE MODEL ---
# Features: [Age, Total Bilirubin, Direct Bilirubin, Albumin]
liver_X = [[25, 0.5, 0.1, 4.0], [45, 1.2, 0.5, 3.5], [60, 3.5, 1.5, 2.8], [30, 0.8, 0.2, 4.2]]
liver_y = [0, 0, 1, 0] # 0 = Healthy, 1 = Liver Issue

liver_model = LogisticRegression()
liver_model.fit(liver_X, liver_y)
save_model(liver_model, "liver_model.pkl")
print("✅ Liver Disease Model Saved!")
