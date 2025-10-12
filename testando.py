from flask import Flask, jsonify, request, render_template
import mysql.connector
import pandas as pd
import traceback


app = Flask(__name__)
app.url_map.strict_slashes = False  # evita 404 por barra final

# --- CORS 
@app.after_request
def add_cors_headers(resp):
    
    if request.path.startswith("/api/"):
        origin = request.headers.get("Origin", "*")
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

@app.route("/api/<path:_>", methods=["OPTIONS"])
def cors_preflight(_):
  
    r = jsonify({"ok": True})
    return r, 204


# MySQL

DB_CONFIG = dict(
    host="127.0.0.1",
    port=3306,
    user="root",
    password="Kauan1807@",
    database="tcc",
    ssl_disabled=True,      
    use_pure=True,          
    connection_timeout=10
)

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

#  executa SQL e devolve DataFrame 
def query_df(sql, params=None):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        return pd.DataFrame(rows)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

# Helper: lista colunas de uma tabela
def table_columns(table_name):
    sql = """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
    """
    df = query_df(sql, (DB_CONFIG["database"], table_name))
    return set(df["COLUMN_NAME"].tolist()) if not df.empty else set()

# ---- LOGA TUDO QUE CHEGA ----
@app.before_request
def log_request():
    print(f"[REQ] {request.method} {request.url}  Host: {request.host}  Path: {request.path}")


@app.errorhandler(404)
def not_found(e):
    msg = f"404 (do Flask): você pediu path '{request.path}' neste host/porta '{request.host}'."
    print("[404]", msg)
    return msg, 404


@app.route("/ping")
def ping():
    return "pong", 200


@app.route("/")
def index():
    
    return render_template("index.html")


# 1) Histórico anual

@app.route("/api/incidencia/anual")
def incidencia_anual():
    try:
        start = int(request.args.get("start", 2000))
        end   = int(request.args.get("end", 2023))

        sql = """
            SELECT ano_cmpt AS ano_str
            FROM incidencia_clima_unificado_stage
            WHERE ano_cmpt REGEXP '^[0-9]{4}$'
              AND ano_cmpt BETWEEN %s AND %s
        """
        df = query_df(sql, (str(start), str(end)))
        if df.empty:
            return jsonify([])

        df["ano"] = pd.to_numeric(df["ano_str"], errors="coerce").astype("Int64")
        df = df.dropna(subset=["ano"])
        out = (
            df.groupby("ano", as_index=False)
              .size()
              .rename(columns={"size": "casos"})
              .sort_values("ano")
        )
        return jsonify(out.to_dict(orient="records"))

    except Exception as ex:
        print("[ERRO incidencia_anual]", ex)
        traceback.print_exc()
        return jsonify({"error": "incidencia_anual failed"}), 500


# 2) Preditivo até 2033

@app.route("/api/preditivo/anual")
def preditivo_anual():
    try:
        modelo = request.args.get("modelo", "Prophet")  #  ARIMA | ETS etc.

        sql = """
            SELECT year AS ano, model AS modelo, point, lo95, hi95
            FROM resultadosprevisoes_cancer_pele
            ORDER BY ano
        """
        df = query_df(sql)
        if df.empty:
            return jsonify([])

        df["modelo"] = df["modelo"].astype(str)
        df = df[df["modelo"].str.upper() == modelo.upper()]
        return jsonify(df.to_dict(orient="records"))

    except Exception as ex:
        print("[ERRO preditivo_anual]", ex)
        traceback.print_exc()
        return jsonify({"error": "preditivo_anual failed"}), 500


# 3) Correlação UV × Casos

@app.route("/api/correlacao/uv-incidencia")
def correlacao_uv():
    try:
        start = int(request.args.get("start", 2000))
        end   = int(request.args.get("end", 2023))

        # 3.1) Casos por ano
        sql_casos = """
            SELECT ano_cmpt AS ano_str
            FROM incidencia_clima_unificado_stage
            WHERE ano_cmpt REGEXP '^[0-9]{4}$'
              AND ano_cmpt BETWEEN %s AND %s
        """
        df_casos = query_df(sql_casos, (str(start), str(end)))
        if df_casos.empty:
            return jsonify([])

        df_casos["ano"] = pd.to_numeric(df_casos["ano_str"], errors="coerce").astype("Int64")
        df_casos = df_casos.dropna(subset=["ano"])
        df_casos = (
            df_casos.groupby("ano", as_index=False)
                    .size()
                    .rename(columns={"size": "casos"})
        )

        # 3.2) UV por ano 
        cols = table_columns("resultadosprevisoes_cancer_pele")

        year_col = "year" if "year" in cols else ("ano" if "ano" in cols else None)
        uv_candidates = ["indice_uv", "uv", "uv_index", "indiceUV", "uv_medio", "uvmedia", "indiceuv"]
        uv_col = next((c for c in uv_candidates if c in cols), None)

        if not year_col or not uv_col:
            print(f"[WARN] Sem colunas de UV/ANO -> year_col={year_col}, uv_col={uv_col}")
            df_casos["uv_medio"] = None
            return jsonify(df_casos.sort_values("ano").to_dict(orient="records"))

        if year_col == "year":
            sql_uv = f"""
                SELECT {year_col} AS ano_raw, {uv_col} AS uv_raw
                FROM resultadosprevisoes_cancer_pele
                WHERE {year_col} BETWEEN %s AND %s
                  AND {uv_col} IS NOT NULL
                  AND {uv_col} <> ''
            """
            params_uv = (start, end)
        else:  
            sql_uv = f"""
                SELECT {year_col} AS ano_raw, {uv_col} AS uv_raw
                FROM resultadosprevisoes_cancer_pele
                WHERE {year_col} REGEXP '^[0-9]{{4}}$'
                  AND {year_col} BETWEEN %s AND %s
                  AND {uv_col} IS NOT NULL
                  AND {uv_col} <> ''
            """
            params_uv = (str(start), str(end))

        df_uv = query_df(sql_uv, params_uv)
        if df_uv.empty:
            df_casos["uv_medio"] = None
            return jsonify(df_casos.sort_values("ano").to_dict(orient="records"))

        # normaliza UV (vírgula -> ponto) e converte
        df_uv["uv_raw"] = df_uv["uv_raw"].astype(str).str.replace(",", ".", regex=False)
        df_uv["uv_val"] = pd.to_numeric(df_uv["uv_raw"], errors="coerce")

        # normaliza ano
        df_uv["ano"] = pd.to_numeric(df_uv["ano_raw"], errors="coerce").astype("Int64")
        df_uv = df_uv.dropna(subset=["ano", "uv_val"])

        df_uv = (
            df_uv.groupby("ano", as_index=False)["uv_val"]
                 .mean()
                 .rename(columns={"uv_val": "uv_medio"})
        )

        # 3.3) junta mantendo todos os anos com casos
        out = df_casos.merge(df_uv, on="ano", how="left").sort_values("ano")
        return jsonify(out.to_dict(orient="records"))

    except Exception as ex:
        print("[ERRO correlacao_uv]", ex)
        traceback.print_exc()
        return jsonify({"error": "correlacao_uv failed"}), 500


# MAIN

if __name__ == "__main__":   
    with app.app_context():
        print("\n=== URL MAP (testando.py) ===")
        print(app.url_map)
        print("=============================\n")
    app.run(host="127.0.0.1", port=5051, debug=True)