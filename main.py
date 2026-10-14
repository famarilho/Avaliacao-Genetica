from auditoria import auditar_e_preparar_dados
from blup import executar_blup_bivariado

if __name__ == "__main__":
    print("1. Executando Auditoria e Leitura de Dados...")
    data_final, ped_ordenado, all_ids, df_log = auditar_e_preparar_dados(
        "Dados_Peso.xlsx", 
        "Pedigree.xlsx", 
        "Dados_dam.xlsx"
    )

    print("2. Executando Avaliação Genética BLUP...")
    # Valores de parâmetros genéticos (exemplo dos valores padrão do seu script)
    relatorio_geral = executar_blup_bivariado(
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

    print("\nAvaliação Genética concluída com sucesso!")
    print(relatorio_geral[['Name', 'DEP_PD', 'DEP_MAT_PD', 'DEP_PPD', 'Indice', 'Perc_Indice']].head(10))