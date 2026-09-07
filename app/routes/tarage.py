from flask import Blueprint, render_template, request, jsonify,  current_app, redirect, url_for
from app.services.security import jwt_required_or_redirect
import pandas as pd
import numpy as np

from app.config import Config
from app.sta_tools import sta_client
# from app.services.utils import allowed_file

ALLOWED_EXTENSIONS = {'csv'}

tarage_bp = Blueprint('tarage', __name__)


def convert_time(col, delta_t):
    # tentative conversion datetime
    dt = pd.to_datetime(col, errors="coerce")

    # détecter les "fausses dates" (1970 ou NaT)
    mask_bad = dt.isna() | (dt.dt.year == 1970)

    # remplacer par delta_t * valeur en secondes
    dt.loc[mask_bad] = pd.to_datetime(
        col[mask_bad] * delta_t,
        unit="s"
    )

    return dt


@tarage_bp.get('/dilution')
@jwt_required_or_redirect()
def starter():
    """
    page acceuil
    """
    param = {
        "$filter": "MultiDatastreams/ObservedProperties/name eq 'stream stage'",
        "$select": "name,id"
    }
    r = sta_client.get("archive", "/Things", params=param)
    print(r.url)
    if not r.ok:
        return jsonify({"error": "impossible to reach the SensorThings"}), 401
    data = r.json()['value']

    return render_template('private/dilution.html', exutoire=data)


@tarage_bp.post('/calculate-debit')
@jwt_required_or_redirect()
def calcul_debit():
    data = request.form.to_dict()

    if 'input_data1' not in request.files:
        return jsonify({"error": "Aucun csv envoyé"}), 400

    file1 = request.files['input_data1']
    if file1.filename == '':
        return jsonify({"error": "Nom de fichier invalide"}), 400
    file2 = request.files['input_data2']
    file3 = request.files['input_data3']
    # if file and allowed_file(file.filename, ALLOWED_EXTENSIONS):
    idx = 1
    df_final = pd.DataFrame()
    debit = []

    M_Na_Cl = 0.05843
    lambda_Na_Cl = 0.012639
    masse_sel = float(data['masseSel'])
    delta_t = float(data['intervalle'])
    conductivite_init = float(data['conductiviteInit'])/10000
    zz = 0
    for i in [file1, file2, file3]:
        print('###############################################')
        print(zz)
        zz += 1
        print('###############################################')
        df = pd.read_csv(i)

        df["time"] = convert_time(df["time"], delta_t)

        df['delta_Cm_kg_m3'] = (M_Na_Cl/lambda_Na_Cl) * \
            ((df['conductivity']/10000) - conductivite_init)

        # y = df['delta_conductivity'].values
        # area = np.trapz(y)
        # print(idx, "area =", area)

        integration = sum(df['delta_Cm_kg_m3'])
        print(integration)
        debit_idx = round(masse_sel/integration / delta_t*1000, 2)

        debit.append(debit_idx)
        df = df.rename(columns={'conductivity': f'conductivity_{idx}'})
        df_final = pd.concat([df_final, df[['time', f'conductivity_{idx}']]])
        idx += 1

    df_final = df_final.replace({np.nan: None})
    dataArray = {
        "components": df_final.columns.tolist(),
        "values": df_final.values.tolist()
    }
    if idx < 6:
        incertitude = (np.max(debit)-np.min(debit)) / \
            (np.sqrt(3)*np.mean(debit))
    else:
        incertitude = np.std(debit)/np.mean(debit)
    print("finish")
    return jsonify({"debit": debit, "dataArray": dataArray, "incertitude": round(incertitude*100, 2)})
