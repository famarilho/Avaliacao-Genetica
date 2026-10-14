import gradio as gr
import pandas as pd
import tempfile
import os
from auditoria import auditar_e_preparar_dados
from blup import executar_blup_bivariado

def processar_avaliacao(file_dados, file_ped, file_dam):
    if not file_dados or not file_ped or not file_dam:
        return "⚠️ Por favor, carregue os três ficheiros Excel antes de continuar.", None, None

    try:
        # 1. Leitura e Auditoria de Dados
        data_final, ped_ordenado, all_ids, df_log = auditar_e_preparar_dados(
            file_dados.name, file_ped.name, file_dam.name
        )

        # 2. Resolução das MMEs / BLUP
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

        # Selecionar colunas principais para visualização
        df_vis = relatorio[['Name', 'Sire', 'Dam', 'Sex', 'Birth.year', 'DEP_PD', 'DEP_MAT_PD', 'DEP_PPD', 'Indice', 'Perc_Indice']]
        
        # Guardar ficheiro CSV temporário para descarregar
        temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        relatorio.to_csv(temp_csv.name, index=False, encoding='utf-8-sig')

        msg_status = f"✅ Avaliação Genética concluída com sucesso!\nTotal de animais avaliados: {len(relatorio)}\nTotal de registos excluídos: {len(df_log)}"

        return msg_status, df_vis, temp_csv.name, df_log

    except Exception as e:
        return f"❌ Erro ao processar a avaliação: {str(e)}", None, None, None


# Construção da Interface Gráfica
with gr.Blocks(title="Avaliação Genética Texel", theme=gr.themes.Soft()) as app:
    gr.Markdown("# 🐑 Avaliação Genética Texel")
    gr.Markdown("Aplicação gratuita para avaliação genética de ovinos em Python.")

    with gr.Row():
        f_dados = gr.File(label="1. Desempenho (Dados_Peso.xlsx)", file_types=[".xlsx"])
        f_ped = gr.File(label="2. Pedigree (Pedigree.xlsx)", file_types=[".xlsx"])
        f_dam = gr.File(label="3. Dados das Mães (Dados_dam.xlsx)", file_types=[".xlsx"])

    btn_executar = gr.Button("🚀 Executar Avaliação Genética", variant="primary")
    
    out_status = gr.Textbox(label="Status do Processamento", interactive=False)

    with gr.Tab("📊 DEPs e Índices"):
        out_tabela = gr.Dataframe(label="Relatório Geral de DEPs")
        out_download = gr.File(label="📥 Descarregar Relatório Completo (CSV)")

    with gr.Tab("⚠️ Registos Excluídos"):
        out_log = gr.Dataframe(label="Log de Auditoria e Exclusões")

    btn_executar.click(
        fn=processar_avaliacao,
        inputs=[f_dados, f_ped, f_dam],
        outputs=[out_status, out_tabela, out_download, out_log]
    )

if __name__ == "__main__":
    app.launch(inbrowser=True)