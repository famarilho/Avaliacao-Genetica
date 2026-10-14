import pandas as pd
import numpy as np
from datetime import datetime

def auditar_e_preparar_dados(caminho_dados, caminho_ped, caminho_dam):
    """
    Lê os arquivos Excel, audita duplicados, ordena o pedigree e filtra
    grupos contemporâneos com menos de 5 animais.
    """
    # 1. Leitura das planilhas Excel
    df_dados = pd.read_excel(caminho_dados)
    df_ped = pd.read_excel(caminho_ped)
    df_dam = pd.read_excel(caminho_dam)

    # Converter colunas de ID para string
    df_dados['Name'] = df_dados['Name'].astype(str).str.strip()
    for col in ['Name', 'Sire', 'Dam']:
        if col in df_ped.columns:
            df_ped[col] = df_ped[col].astype(str).str.strip()
    df_dam['Dam'] = df_dam['Dam'].astype(str).str.strip()
    df_dam['Birth.date.dam'] = pd.to_datetime(df_dam['Birth.date.dam'])

    # Estrutura para registrar exclusões (Log de Auditoria)
    log_exclusoes = []

    # 2. Identificação de IDs duplicados
    duplicados = df_dados[df_dados.duplicated(subset=['Name'], keep=False)]
    if not duplicados.empty:
        for name in duplicados['Name'].unique():
            log_exclusoes.append({
                'Name': name,
                'Motivo_Exclusao': 'ID Duplicado na Base',
                'Detalhe': 'Registro duplicado na planilha. Removido por precaução.'
            })
    
    df_dados_sem_dups = df_dados[~df_dados['Name'].isin(duplicados['Name'])].copy()

    # 3. Tratamento e Ordenação do Pedigree
    df_ped['Sire'] = df_ped['Sire'].replace(['nan', 'NA', '', '*', 'None'], '0')
    df_ped['Dam'] = df_ped['Dam'].replace(['nan', 'NA', '', '*', 'None'], '0')
    df_ped = df_ped.drop_duplicates(subset=['Name'])

    # Adicionar pais ausentes no pedigree
    pais_presentes = set(df_ped['Sire'].unique()).union(set(df_ped['Dam'].unique())) - {'0'}
    animais_ped = set(df_ped['Name'].unique())
    pais_ausentes = pais_presentes - animais_ped

    if pais_ausentes:
        df_ausentes = pd.DataFrame({'Name': list(pais_ausentes), 'Sire': '0', 'Dam': '0'})
        df_ped = pd.concat([df_ausentes, df_ped], ignore_index=True)

    if '0' not in df_ped['Name'].values:
        df_zero = pd.DataFrame({'Name': ['0'], 'Sire': [None], 'Dam': [None]})
        df_ped = pd.concat([df_zero, df_ped], ignore_index=True)

    # Função de ordenação topológica do pedigree (garante ancestral antes do descendente)
    res_ped = []
    pendentes = df_ped.copy()
    
    while not pendentes.empty:
        nomes_resolvidos = set([r['Name'] for r in res_ped])
        prontos = pendentes[
            (pendentes['Dam'].isin(nomes_resolvidos) | (pendentes['Dam'] == '0') | pendentes['Dam'].isna()) &
            (pendentes['Sire'].isin(nomes_resolvidos) | (pendentes['Sire'] == '0') | pendentes['Sire'].isna())
        ]
        
        if prontos.empty:
            raise ValueError("Erro: Inconsistência ou loop circular detectado no pedigree.")
            
        res_ped.extend(prontos.to_dict('records'))
        pendentes = pendentes[~pendentes['Name'].isin(prontos['Name'])]

    ped_ordenado = pd.DataFrame(res_ped)
    all_ids = ped_ordenado['Name'].tolist()

    # 4. Cruzamento de dados e cálculo de idades
    df_dam_unique = df_dam.drop_duplicates(subset=['Dam'])

    df_edit = df_dados_sem_dups.merge(df_ped[['Name', 'Dam', 'Sire']], on='Name', how='left')
    df_edit = df_edit.merge(df_dam_unique[['Dam', 'Birth.date.dam']], on='Dam', how='left')
    df_edit = df_edit.drop_duplicates(subset=['Name'])

    df_edit['Dam'] = df_edit['Dam'].fillna('0').replace(['nan', 'NA', ''], '0')
    df_edit['Birth.date'] = pd.to_datetime(df_edit['Birth.date'])
    df_edit['Weaning.date'] = pd.to_datetime(df_edit['Weaning.date'])
    df_edit['WPW.date'] = pd.to_datetime(df_edit['WPW.date'])

    df_edit['Birth.year'] = df_edit['Birth.date'].dt.year
    df_edit['age_dam'] = (df_edit['Birth.date'] - df_edit['Birth.date.dam']).dt.days / 365.25
    df_edit['Weaning.age'] = (df_edit['Weaning.date'] - df_edit['Birth.date']).dt.days
    df_edit['Post.Weaning.age'] = (df_edit['WPW.date'] - df_edit['Birth.date']).dt.days

    # Criação dos Grupos Contemporâneos (GC)
    df_edit['CG_weaning'] = (
        df_edit['Ranch'].astype(str) + '_' +
        df_edit['Birth.year'].astype(str) + '_' +
        df_edit['Sex'].astype(str) + '_' +
        df_edit['Weaning.batch'].astype(str)
    )

    df_edit['CG_Post_weaning'] = (
        df_edit['CG_weaning'] + '_' +
        df_edit['Post.weaning.batch'].astype(str)
    )

    # 5. Filtragem de Grupos Contemporâneos (N < 5)
    cg_w_counts = df_edit['CG_weaning'].value_counts()
    cg_pw_counts = df_edit['CG_Post_weaning'].value_counts()

    df_edit['n_cg_w'] = df_edit['CG_weaning'].map(cg_w_counts)
    df_edit['n_cg_pw'] = df_edit['CG_Post_weaning'].map(cg_pw_counts)

    excluidos_cg = df_edit[(df_edit['n_cg_w'] < 5) | (df_edit['n_cg_pw'] < 5)]
    for _, row in excluidos_cg.iterrows():
        log_exclusoes.append({
            'Name': row['Name'],
            'Motivo_Exclusao': 'Grupo Contemporâneo Pequeno (N < 5)',
            'Detalhe': f"CG_Desmame: {row['CG_weaning']} (N={row['n_cg_w']}) | CG_PósDesmame: {row['CG_Post_weaning']} (N={row['n_cg_pw']})"
        })

    data_final = df_edit[(df_edit['n_cg_w'] >= 5) & (df_edit['n_cg_pw'] >= 5)].copy()

    # Preenchimento de idades de mãe ausentes com a média
    media_idade_mae = data_final['age_dam'].mean()
    data_final['age_dam'] = data_final['age_dam'].fillna(media_idade_mae)

    df_log = pd.DataFrame(log_exclusoes)

    return data_final, ped_ordenado, all_ids, df_log
if __name__ == "__main__":
    data_final, ped_ordenado, all_ids, df_log = auditar_e_preparar_dados(
        "Dados_Peso.xlsx", 
        "Pedigree.xlsx", 
        "Dados_dam.xlsx"
    )
    print(f"Processamento concluído!")
    print(f"Total de animais no pedigree: {len(all_ids)}")
    print(f"Total de animais com dados filtrados: {len(data_final)}")
    print(f"Total de registros excluídos: {len(df_log)}")