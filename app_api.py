from fastapi import FastAPI, UploadFile, File
import pandas as pd
import tempfile
import os
from auditoria import auditar_e_preparar_dados
from blup import executar_blup_bivariado

# ATENÇÃO: O nome dessa variável DEVE ser 'app' (tudo em minúsculo)
app = FastAPI(title="API de Avaliação Genética Texel")

@app.get("/")
def home():
    return {"mensagem": "API de Avaliação Genética no ar com sucesso!"}

@app.post("/avaliar")
async def avaliar_genetica(
    file_dados: UploadFile = File(...),
    file_ped: UploadFile = File(...),
    file_dam: UploadFile = File(...)
):
    # Salvar temporariamente os arquivos enviados pelo aplicativo
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_dados, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_ped, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_dam:
        
        tmp_dados.write(await file_dados.read())
        tmp_ped.write(await file_ped.read())
        tmp_dam.write(await file_dam.read())

        path_dados = tmp_dados.name
        path_ped = tmp_ped.name
        path_dam = tmp_dam.name

    try:
        # 1. Auditoria e Leitura
        data_final, ped_ordenado, all_ids, df_log = auditar_e_preparar_dados(
            path_dados, path_ped, path_dam
        )

        # 2. Execução do BLUP
        relatorio = executar_blup_bivariado(
            data_final=data_final,
            ped_ordenado=ped_ordenado,
            all_ids=all_ids,
            va_dir_pd=12.5,
            va_mat_pd=4.2,
            ve_pd=18.0,
            va_ppd=22.0,
            ve_ppd=25.0,
            cov_g_pd_ppd=8.5
        )

        return {
            "status": "sucesso",
            "total_avaliados": len(relatorio),
            "total_excluidos": len(df_log),
            "exclusoes": df_log.to_dict(orient="records"),
            "resultados": relatorio[['Name', 'DEP_PD', 'DEP_MAT_PD', 'DEP_PPD', 'Indice', 'Perc_Indice']].to_dict(orient="records")
        }

    finally:
        os.remove(path_dados)
        os.remove(path_ped)
        os.remove(path_dam)