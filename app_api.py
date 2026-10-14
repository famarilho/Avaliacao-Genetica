from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import numpy as np
import io
import os
import zipfile
import base64
import tempfile
from typing import Optional

from auditoria import auditar_e_preparar_dados
from blup import executar_blup_bivariado

app = FastAPI(title="API de Avaliação Genética Texel")

# Configuração de CORS permissiva para aceitar requisições do GitHub Pages / Pinggy / Ngrok
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

@app.get("/")
def home():
    return {"mensagem": "API de Avaliação Genética no ar com sucesso!"}

# Trata requisições preflight (OPTIONS) do navegador para qualquer rota sem bloqueios CORS
@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    return {}

def ler_parametros_txt(conteudo_txt: str) -> dict:
    """Extrai os parâmetros genéticos a partir do arquivo TXT gerado pelo R."""
    def extrair_val(chave, texto):
        for linha in texto.splitlines():
            if chave in linha:
                parts = linha.split(":")
                if len(parts) > 1:
                    try:
                        return float(parts[1].strip())
                    except ValueError:
                        return 0.0
        return 0.0

    va_dir_pd = extrair_val("Va_dir_pd", conteudo_txt)
    va_mat_pd = extrair_val("Va_mat_pd", conteudo_txt)
    ve_pd     = extrair_val("Ve_pd", conteudo_txt)
    va_ppd    = extrair_val("Va_ppd", conteudo_txt)
    ve_ppd    = extrair_val("Ve_ppd", conteudo_txt)
    cov_g     = extrair_val("PD x PPD", conteudo_txt)

    h2_dir_pd = extrair_val("h2_dir_pd", conteudo_txt)
    h2_mat_pd = extrair_val("h2_mat_pd", conteudo_txt)
    h2_ppd    = extrair_val("h2_ppd", conteudo_txt)

    if va_dir_pd == 0 or va_ppd == 0:
        raise ValueError("O arquivo de parâmetros genéticos está num formato inválido ou com valores zerados.")

    return {
        'va_dir_pd': va_dir_pd, 'va_mat_pd': va_mat_pd, 've_pd': ve_pd,
        'va_ppd': va_ppd, 've_ppd': ve_ppd, 'cov_g_pd_ppd': cov_g,
        'h2_dir_pd': h2_dir_pd, 'h2_mat_pd': h2_mat_pd, 'h2_ppd': h2_ppd
    }

def montar_relatorio_individual(df_input: pd.DataFrame) -> pd.DataFrame:
    """Monta estrutura de 3 linhas por animal (DEP, Acurácia, Top %) conforme a função R."""
    rows = []
    for _, row in df_input.iterrows():
        name = str(row['Name'])
        rows.append({
            'FBB_ANI': name, 'NOME': name, 'Indicador': 'DEP',
            'DEP_PD': round(float(row['DEP_PD']), 2),
            'DEP_MAT_PD': round(float(row['DEP_MAT_PD']), 2),
            'DEP_PPD': round(float(row['DEP_PPD']), 2),
            'Indice': round(float(row['Indice']), 2)
        })
        rows.append({
            'FBB_ANI': name, 'NOME': name, 'Indicador': 'Acurácia',
            'DEP_PD': round(float(row['Acuracia_DIR_PD']), 2),
            'DEP_MAT_PD': round(float(row['Acuracia_MAT_PD']), 2),
            'DEP_PPD': round(float(row['Acuracia_PPD']), 2),
            'Indice': np.nan
        })
        rows.append({
            'FBB_ANI': name, 'NOME': name, 'Indicador': 'Top %',
            'DEP_PD': int(row['Perc_DEP_PD']),
            'DEP_MAT_PD': int(row['Perc_DEP_MAT_PD']),
            'DEP_PPD': int(row['Perc_DEP_PPD']),
            'Indice': int(row['Perc_Indice'])
        })
    return pd.DataFrame(rows)

def montar_relatorio_pais(df_input: pd.DataFrame, relatorio_geral: pd.DataFrame, id_col: str, nome_id: str) -> pd.DataFrame:
    """Monta estrutura de 3 linhas por pai/mãe com contagem de progênies conforme a função R."""
    rows = []
    col_fbb = f"FBB_{nome_id}"
    col_nome = f"NOME_{nome_id}"

    for _, row in df_input.iterrows():
        name = str(row['Name'])
        prog_count = int((relatorio_geral[id_col] == name).sum())

        rows.append({
            col_fbb: name, col_nome: name, 'Progenies': prog_count, 'Indicador': 'DEP',
            'DEP_PD': round(float(row['DEP_PD']), 2),
            'DEP_MAT_PD': round(float(row['DEP_MAT_PD']), 2),
            'DEP_PPD': round(float(row['DEP_PPD']), 2),
            'Indice': round(float(row['Indice']), 2)
        })
        rows.append({
            col_fbb: name, col_nome: name, 'Progenies': prog_count, 'Indicador': 'Acurácia',
            'DEP_PD': round(float(row['Acuracia_DIR_PD']), 2),
            'DEP_MAT_PD': round(float(row['Acuracia_MAT_PD']), 2),
            'DEP_PPD': round(float(row['Acuracia_PPD']), 2),
            'Indice': np.nan
        })
        rows.append({
            col_fbb: name, col_nome: name, 'Progenies': prog_count, 'Indicador': 'Top %',
            'DEP_PD': int(row['Perc_DEP_PD']),
            'DEP_MAT_PD': int(row['Perc_DEP_MAT_PD']),
            'DEP_PPD': int(row['Perc_DEP_PPD']),
            'Indice': int(row['Perc_Indice'])
        })
    return pd.DataFrame(rows)

def gerar_relatorios_excel(relatorio_df: pd.DataFrame, df_log: pd.DataFrame, data_final: pd.DataFrame, params: dict, n_total_dados: int) -> dict:
    """Gera todas as planilhas Excel formatadas e empacota em Base64 e .ZIP."""
    relatorio_df['Birth.year'] = pd.to_numeric(relatorio_df['Birth.year'], errors='coerce')
    data_final['Birth.year'] = pd.to_numeric(data_final['Birth.year'], errors='coerce')
    
    ultimo_ano = relatorio_df['Birth.year'].max()
    if pd.isna(ultimo_ano):
        ultimo_ano = data_final['Birth.year'].max()

    relatorio_df['Sex_norm'] = relatorio_df['Sex'].astype(str).str.strip().str.upper()

    arquivos_b64 = {}

    def to_b64(df_dict_or_df):
        buf = io.BytesIO()
        if isinstance(df_dict_or_df, dict):
            with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                for sheet, df in df_dict_or_df.items():
                    df.to_excel(writer, sheet_name=sheet, index=False)
        else:
            df_dict_or_df.to_excel(buf, index=False)
        return base64.b64encode(buf.getvalue()).decode('utf-8')

    # 1. Percentis.xlsx
    probs_target = [0.99, 0.95, 0.90, 0.75, 0.50, 0.25, 0.10, 0.05, 0.01]
    labels = ["Melhor", "1%", "5%", "10%", "25%", "50%", "75%", "90%", "95%", "99%", "Pior"]

    def calc_quantiles(series):
        return [series.max()] + [series.quantile(p) for p in probs_target] + [series.min()]

    df_percentis = pd.DataFrame({
        'Percentil': labels,
        'DEP_PD': np.round(calc_quantiles(relatorio_df['DEP_PD']), 2),
        'DEP_MAT_PD': np.round(calc_quantiles(relatorio_df['DEP_MAT_PD']), 2),
        'DEP_PPD': np.round(calc_quantiles(relatorio_df['DEP_PPD']), 2),
        'Indice': np.round(calc_quantiles(relatorio_df['Indice']), 2)
    })
    arquivos_b64["Percentis.xlsx"] = to_b64(df_percentis)

    # 2. RESUMO.xlsx
    machos_cnt = len(relatorio_df[relatorio_df['Sex_norm'].isin(['1', 'M', 'MALE', '1.0'])])
    femeas_cnt = len(relatorio_df[relatorio_df['Sex_norm'].isin(['2', 'F', 'FEMALE', '2.0'])])
    ult_ano_cnt = len(relatorio_df[relatorio_df['Birth.year'] == ultimo_ano])
    sires_cnt = relatorio_df['Sire'].astype(str).str.strip().replace(['0', 'NA', '', '0.0', 'nan'], np.nan).dropna().nunique()
    dams_cnt = relatorio_df['Dam'].astype(str).str.strip().replace(['0', 'NA', '', '0.0', 'nan'], np.nan).dropna().nunique()

    resumo_sheets = {
        'Fenotipos': pd.DataFrame({
            'Variavel': ['Peso_Desmame', 'Peso_Pos_Desmame'],
            'Observacoes_usadas': [len(data_final.dropna(subset=['Weaning.weight'])), len(data_final.dropna(subset=['Weight.PW']))],
            'Total_registros': [n_total_dados, n_total_dados]
        }),
        'DEPS': pd.DataFrame({
            'Variavel': ['Machos', 'Fêmeas', 'Geração Ultimo Ano', 'Carneiros', 'Ovelhas', 'Total'],
            'DEPS': [machos_cnt, femeas_cnt, ult_ano_cnt, sires_cnt, dams_cnt, len(relatorio_df)]
        }),
        'Idades': pd.DataFrame({
            'Idade_Desmame': [round(float(data_final['Weaning.age'].mean()), 1)],
            'Idade_Pos_Desmame': [round(float(data_final['Post.Weaning.age'].mean()), 1)],
            'Idade_Mae': [round(float(data_final['age_dam'].mean()), 1)]
        }),
        'Indice': pd.DataFrame({
            'Indice': ['Indice Texel Base 100'],
            'Formula': ['100 + 25% * DEP_PD + 25% * DEP_MAT_PD + 50% * DEP_PPD']
        }),
        'Parametros Geneticos': pd.DataFrame({
            'Efeito': ['Peso Desmame Direto', 'Peso Desmame Materno', 'Peso Pos-Desmame'],
            'Variancia_Aditiva': np.round([params['va_dir_pd'], params['va_mat_pd'], params['va_ppd']], 4),
            'Variancia_Residual': np.round([params['ve_pd'], params['ve_pd'], params['ve_ppd']], 4),
            'Herdabilidade': np.round([params['h2_dir_pd'], params['h2_mat_pd'], params['h2_ppd']], 3)
        })
    }
    arquivos_b64["RESUMO.xlsx"] = to_b64(resumo_sheets)

    # 3. Relatórios Machos, Fêmeas e Pais
    machos_safra = relatorio_df[(relatorio_df['Birth.year'] == ultimo_ano) & (relatorio_df['Sex_norm'].isin(['1', 'M', 'MALE', '1.0']))].sort_values(by='Indice', ascending=False)
    if len(machos_safra) == 0:
        machos_safra = relatorio_df[relatorio_df['Sex_norm'].isin(['1', 'M', 'MALE', '1.0'])].sort_values(by='Indice', ascending=False)
    arquivos_b64["Relatório Machos.xlsx"] = to_b64(montar_relatorio_individual(machos_safra))

    femeas_safra = relatorio_df[(relatorio_df['Birth.year'] == ultimo_ano) & (relatorio_df['Sex_norm'].isin(['2', 'F', 'FEMALE', '2.0']))].sort_values(by='Indice', ascending=False)
    if len(femeas_safra) == 0:
        femeas_safra = relatorio_df[relatorio_df['Sex_norm'].isin(['2', 'F', 'FEMALE', '2.0'])].sort_values(by='Indice', ascending=False)
    arquivos_b64["Relatório Femeas.xlsx"] = to_b64(montar_relatorio_individual(femeas_safra))

    ids_carneiros = machos_safra['Sire'].astype(str).str.strip().replace(['0', 'NA', '', '0.0', 'nan'], np.nan).dropna().unique()
    carneiros = relatorio_df[relatorio_df['Name'].astype(str).isin(ids_carneiros)].sort_values(by='Indice', ascending=False)
    if len(carneiros) == 0:
        all_sires = relatorio_df['Sire'].astype(str).str.strip().replace(['0', 'NA', '', '0.0', 'nan'], np.nan).dropna().unique()
        carneiros = relatorio_df[relatorio_df['Name'].astype(str).isin(all_sires)].sort_values(by='Indice', ascending=False)
    arquivos_b64["Relatório Carneiros.xlsx"] = to_b64(montar_relatorio_pais(carneiros, relatorio_df, 'Sire', 'PAI'))

    dams_safra = relatorio_df[relatorio_df['Birth.year'] == ultimo_ano]['Dam'].astype(str).str.strip().replace(['0', 'NA', '', '0.0', 'nan'], np.nan).dropna().unique()
    ovelhas = relatorio_df[relatorio_df['Name'].astype(str).isin(dams_safra)].sort_values(by='DEP_MAT_PD', ascending=False)
    if len(ovelhas) == 0:
        all_dams = relatorio_df['Dam'].astype(str).str.strip().replace(['0', 'NA', '', '0.0', 'nan'], np.nan).dropna().unique()
        ovelhas = relatorio_df[relatorio_df['Name'].astype(str).isin(all_dams)].sort_values(by='DEP_MAT_PD', ascending=False)
    arquivos_b64["Relatório Ovelhas.xlsx"] = to_b64(montar_relatorio_pais(ovelhas, relatorio_df, 'Dam', 'MAE'))

    arquivos_b64["02_prestacao_contas_exclusoes.xlsx"] = to_b64(df_log)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for fname, b64_str in arquivos_b64.items():
            zip_file.writestr(fname, base64.b64decode(b64_str))
            
    arquivos_b64["Pacote_Completo.zip"] = base64.b64encode(zip_buffer.getvalue()).decode('utf-8')

    return arquivos_b64

@app.post("/avaliar")
async def avaliar_genetica(
    file_dados: UploadFile = File(...),
    file_ped: UploadFile = File(...),
    file_dam: UploadFile = File(...),
    file_params: UploadFile = File(...)
):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_dados, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_ped, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_dam:
        
        tmp_dados.write(await file_dados.read())
        tmp_ped.write(await file_ped.read())
        tmp_dam.write(await file_dam.read())

        path_dados, path_ped, path_dam = tmp_dados.name, tmp_ped.name, tmp_dam.name

    try:
        conteudo_txt = (await file_params.read()).decode('utf-8')
        params = ler_parametros_txt(conteudo_txt)

        df_dados_raw = pd.read_excel(path_dados)
        n_total_dados = len(df_dados_raw)

        data_final, ped_ordenado, all_ids, df_log = auditar_e_preparar_dados(
            path_dados, path_ped, path_dam
        )

        relatorio = executar_blup_bivariado(
            data_final=data_final,
            ped_ordenado=ped_ordenado,
            all_ids=all_ids,
            va_dir_pd=params['va_dir_pd'],
            va_mat_pd=params['va_mat_pd'],
            ve_pd=params['ve_pd'],
            va_ppd=params['va_ppd'],
            ve_ppd=params['ve_ppd'],
            cov_g_pd_ppd=params['cov_g_pd_ppd']
        )

        arquivos_excel = gerar_relatorios_excel(relatorio, df_log, data_final, params, n_total_dados)

        return {
            "status": "sucesso",
            "total_avaliados": len(relatorio),
            "total_excluidos": len(df_log),
            "exclusoes": df_log.to_dict(orient="records"),
            "resultados": relatorio[['Name', 'DEP_PD', 'DEP_MAT_PD', 'DEP_PPD', 'Indice', 'Perc_Indice']].to_dict(orient="records"),
            "parametros_txt": conteudo_txt,
            "arquivos": arquivos_excel
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if os.path.exists(path_dados): os.remove(path_dados)
        if os.path.exists(path_ped): os.remove(path_ped)
        if os.path.exists(path_dam): os.remove(path_dam)