import streamlit as st
import pandas as pd
from auditoria import auditar_e_preparar_dados
from blup import executar_blup_bivariado

# Configuração da página (otimizada para telas de telemóvel e computador)
st.set_page_config(
    page_title="Avaliação Genética Texel",
    page_icon="🐑",
    layout="wide"
)

# Título do Aplicativo
st.title("🐑 Avaliação Genética Texel")
st.markdown("Ferramenta gratuita para avaliação genética de ovinos.")

# Criar abas para organizar as funções
tab1, tab2, tab3 = st.tabs(["1. Processamento", "2. DEPs & Relatórios", "3. Registos Excluídos"])

with tab1:
    st.subheader("Carregamento dos Ficheiros Excel")
    st.write("Selecione as planilhas da sua propriedade:")

    col1, col2, col3 = st.columns(3)
    with col1:
        file_dados = st.file_uploader("1. Desempenho (Dados_Peso.xlsx)", type=["xlsx"])
    with col2:
        file_ped = st.file_uploader("2. Pedigree (Pedigree.xlsx)", type=["xlsx"])
    with col3:
        file_dam = st.file_uploader("3. Dados das Mães (Dados_dam.xlsx)", type=["xlsx"])

    if st.button("🚀 Executar Avaliação Genética", type="primary", use_container_width=True):
        if file_dados and file_ped and file_dam:
            with st.spinner("A processar os dados e a resolver as equações de modelo misto (BLUP)..."):
                # Salvar temporariamente os ficheiros para a leitura
                with open("temp_dados.xlsx", "wb") as f:
                    f.write(file_dados.getbuffer())
                with open("temp_ped.xlsx", "wb") as f:
                    f.write(file_ped.getbuffer())
                with open("temp_dam.xlsx", "wb") as f:
                    f.write(file_dam.getbuffer())

                # 1. Auditoria e Leitura
                data_final, ped_ordenado, all_ids, df_log = auditar_e_preparar_dados(
                    "temp_dados.xlsx", "temp_ped.xlsx", "temp_dam.xlsx"
                )

                # 2. Resolução do BLUP
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

                # Guardar resultados na sessão do Streamlit
                st.session_state['relatorio'] = relatorio
                st.session_state['log_exclusoes'] = df_log
                st.session_state['processado'] = True

                st.success("Avaliação Genética concluída com sucesso! NAVEGUE ATÉ À ABA '2. DEPs & Relatórios' para visualizar.")
        else:
            st.error("Por favor, carregue os três ficheiros (.xlsx) antes de executar.")

with tab2:
    st.subheader("Tabela de DEPs e Índices de Seleção")
    if st.session_state.get('processado', False):
        df_res = st.session_state['relatorio']

        # Métricas Rápidas
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Total de Animais Avaliados", len(df_res))
        col_m2.metric("Última Safra Avaliada", int(df_res['Birth.year'].max()))
        col_m3.metric("Média do Índice", round(df_res['Indice'].mean(), 2))

        # Tabela com as DEPs
        st.dataframe(
            df_res[['Name', 'Sire', 'Dam', 'Sex', 'Birth.year', 'DEP_PD', 'DEP_MAT_PD', 'DEP_PPD', 'Indice', 'Perc_Indice']],
            use_container_width=True
        )

        # Botão para Descarregar os Resultados em CSV
        csv_data = df_res.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Descarregar Relatório Completo (CSV)",
            data=csv_data,
            file_name="Relatorio_Avaliacao_Genetica.csv",
            mime="text/csv",
            use_container_width=True
        )
    else:
        st.info("Execute a avaliação na aba '1. Processamento' para visualizar o relatório.")

with tab3:
    st.subheader("Relatório de Prestação de Contas (Registos Excluídos)")
    if st.session_state.get('processado', False):
        df_ex = st.session_state['log_exclusoes']
        if not df_ex.empty:
            st.warning(f"Foram identificados {len(df_ex)} registos com inconsistências ou grupos contemporâneos pequenos.")
            st.dataframe(df_ex, use_container_width=True)
        else:
            st.success("Nenhum registo foi excluído durante o processamento!")
    else:
        st.info("Aguardando execução para gerar o relatório de exclusões.")