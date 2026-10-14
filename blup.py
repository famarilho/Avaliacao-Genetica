import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import spsolve

def construir_A_inversa(ped_ordenado, all_ids):
    """
    Calcula a inversa da matriz de parentesco numérico (A^-1) 
    diretamente pelo método de Henderson (esparso).
    """
    n = len(all_ids)
    id_to_idx = {name: idx for idx, name in enumerate(all_ids)}
    
    # Matriz para acumular as contribuições de A^-1
    rows, cols, vals = [], [], []

    def add_val(r, c, v):
        rows.append(r)
        cols.append(c)
        vals.append(v)

    # Coeficientes de inbreeding / variância de mendeliana (D)
    # Henderson's rules para A^-1 rápida
    L = np.zeros((n, n))
    d_inv = np.zeros(n)

    for i, row in ped_ordenado.iterrows():
        idx_i = id_to_idx[row['Name']]
        sire = row['Sire']
        dam = row['Dam']

        idx_s = id_to_idx[sire] if sire in id_to_idx and sire != '0' else -1
        idx_d = id_to_idx[dam] if dam in id_to_idx and dam != '0' else -1

        # Variância residual do valor genético
        if idx_s != -1 and idx_d != -1:
            f_s = L[idx_s, idx_s] - 1 if idx_s >= 0 else 0
            f_d = L[idx_d, idx_d] - 1 if idx_d >= 0 else 0
            v = 0.5 - 0.25 * (f_s + f_d)
        elif idx_s != -1 or idx_d != -1:
            idx_p = idx_s if idx_s != -1 else idx_d
            f_p = L[idx_p, idx_p] - 1 if idx_p >= 0 else 0
            v = 0.75 - 0.25 * f_p
        else:
            v = 1.0

        alpha = 1.0 / v
        d_inv[idx_i] = alpha

        # Contribuições diretas para a matriz A^-1
        add_val(idx_i, idx_i, alpha)

        if idx_s != -1:
            add_val(idx_i, idx_s, -0.5 * alpha)
            add_val(idx_s, idx_i, -0.5 * alpha)
            add_val(idx_s, idx_s, 0.25 * alpha)

        if idx_d != -1:
            add_val(idx_i, idx_d, -0.5 * alpha)
            add_val(idx_d, idx_i, -0.5 * alpha)
            add_val(idx_d, idx_d, 0.25 * alpha)

        if idx_s != -1 and idx_d != -1:
            add_val(idx_s, idx_d, 0.25 * alpha)
            add_val(idx_d, idx_s, 0.25 * alpha)

    A_inv = sparse.csr_matrix((vals, (rows, cols)), shape=(n, n))
    return A_inv


def calcular_percentil_exato(vec_val):
    """Calcula o percentil exato (Top %) para o índice e DEPs."""
    s = pd.Series(vec_val)
    ranks = s.rank(ascending=False, method='min')
    p = ((ranks - 1) / len(s) * 100).round()
    p = p.clip(lower=1, upper=100)
    return p.astype(int)


def executar_blup_bivariado(data_final, ped_ordenado, all_ids, va_dir_pd, va_mat_pd, ve_pd, va_ppd, ve_ppd, cov_g_pd_ppd):
    """
    Monta as Equações de Modelo Misto (MME), resolve o BLUP bivariado,
    extrai os PEVs/acurácias e gera a tabela com DEPs e Índices.
    """
    n_total = len(all_ids)
    id_to_idx = {name: idx for idx, name in enumerate(all_ids)}

    print("Montando matriz A^-1...")
    A_inv = construir_A_inversa(ped_ordenado, all_ids)

    # 1. Filtro e separação de animais com observações
    df_pd = data_final[data_final['Weaning.weight'].notna()].copy()
    df_ppd = data_final[data_final['Weight.PW'].notna()].copy()

    y_pd = df_pd['Weaning.weight'].values.astype(float)
    y_ppd = df_ppd['Weight.PW'].values.astype(float)
    y_vec = np.concatenate([y_pd, y_ppd])

    # 2. Matrizes de Delineamento dos Efeitos Fixos (X)
    X_pd = pd.get_dummies(df_pd[['CG_weaning', 'Birth.type', 'Birth.weight', 'age_dam', 'Weaning.age']], drop_first=True, dtype=float).values
    X_ppd = pd.get_dummies(df_ppd[['CG_Post_weaning', 'Birth.type', 'Birth.weight', 'Weaning.weight', 'age_dam', 'Post.Weaning.age']], drop_first=True, dtype=float).values

    X_block = sparse.block_diag([sparse.csr_matrix(X_pd), sparse.csr_matrix(X_ppd)], format='csr')

    # 3. Matrizes de Delineamento dos Efeitos Aleatórios (Z)
    n_pd, n_ppd = len(df_pd), len(df_ppd)

    Z_dir_pd = sparse.lil_matrix((n_pd, n_total))
    Z_mat_pd = sparse.lil_matrix((n_pd, n_total))
    for i, (_, r) in enumerate(df_pd.iterrows()):
        Z_dir_pd[i, id_to_idx[r['Name']]] = 1.0
        if r['Dam'] in id_to_idx and r['Dam'] != '0':
            Z_mat_pd[i, id_to_idx[r['Dam']]] = 1.0

    Z_dir_ppd = sparse.lil_matrix((n_ppd, n_total))
    for i, (_, r) in enumerate(df_ppd.iterrows()):
        Z_dir_ppd[i, id_to_idx[r['Name']]] = 1.0

    Z_block = sparse.vstack([
        sparse.hstack([Z_dir_pd, Z_mat_pd, sparse.csr_matrix((n_pd, n_total))]),
        sparse.hstack([sparse.csr_matrix((n_ppd, n_total)), sparse.csr_matrix((n_ppd, n_total)), Z_dir_ppd])
    ], format='csr')

    # 4. Inversa de G0 (Matriz de variância aditiva genômica/genética)
    G0 = np.array([
        [va_dir_pd, 0, cov_g_pd_ppd],
        [0, va_mat_pd, 0],
        [cov_g_pd_ppd, 0, va_ppd]
    ])
    G0_inv = np.linalg.inv(G0)

    # Produto Kronecker G0_inv (x) A_inv
    G_inv = sparse.kron(G0_inv, A_inv, format='csr')

    # Matriz R_inv (resíduos)
    R_inv = sparse.block_diag([
        sparse.diags([1.0 / ve_pd] * n_pd),
        sparse.diags([1.0 / ve_ppd] * n_ppd)
    ], format='csr')

    # 5. Montagem do LHS e RHS
    print("Resolvendo o sistema MME...")
    LHS_11 = X_block.T @ R_inv @ X_block
    LHS_12 = X_block.T @ R_inv @ Z_block
    LHS_21 = Z_block.T @ R_inv @ X_block
    LHS_22 = (Z_block.T @ R_inv @ Z_block) + G_inv

    LHS = sparse.vstack([
        sparse.hstack([LHS_11, LHS_12]),
        sparse.hstack([LHS_21, LHS_22])
    ], format='csc')

    RHS = np.concatenate([
        (X_block.T @ R_inv @ y_vec),
        (Z_block.T @ R_inv @ y_vec)
    ])

    # 6. Resolução da solução u_sol
    u_sol = spsolve(LHS, RHS)

    n_fixed = X_block.shape[1]
    u_random = u_sol[n_fixed:]

    ebv_dir_pd = u_random[0:n_total]
    ebv_mat_pd = u_random[n_total:2*n_total]
    ebv_ppd    = u_random[2*n_total:3*n_total]

    # Aproximação do PEV pela diagonal do inverso esparso do LHS
    # Nota: Em sistemas muito grandes, a aproximação diagnóstica via solutor garante rapidez
    LHS_diag = LHS.diagonal()
    pev_diag = 1.0 / np.maximum(LHS_diag[n_fixed:], 1e-8)

    pev_dir_pd = pev_diag[0:n_total]
    pev_mat_pd = pev_diag[n_total:2*n_total]
    pev_ppd    = pev_diag[2*n_total:3*n_total]

    acu_dir_pd = np.sqrt(np.maximum(0, 1 - (pev_dir_pd / va_dir_pd)))
    acu_mat_pd = np.sqrt(np.maximum(0, 1 - (pev_mat_pd / va_mat_pd)))
    acu_ppd    = np.sqrt(np.maximum(0, 1 - (pev_ppd / va_ppd)))

    # 7. Consolidação dos resultados e bases genéticas
    df_res = pd.DataFrame({'Name': all_ids})
    df_res = df_res.merge(ped_ordenado[['Name', 'Sire', 'Dam']], on='Name', how='left')
    
    meta_animais = data_final[['Name', 'Sex', 'Birth.year']].drop_duplicates(subset=['Name'])
    df_res = df_res.merge(meta_animais, on='Name', how='left')

    df_res['DEP_raw_DIR'] = ebv_dir_pd / 2.0
    df_res['DEP_raw_MAT'] = ebv_mat_pd / 2.0
    df_res['DEP_raw_PPD'] = ebv_ppd / 2.0

    primeiro_ano = df_res['Birth.year'].min()
    base_dir = df_res[df_res['Birth.year'] == primeiro_ano]['DEP_raw_DIR'].mean()
    base_mat = df_res[df_res['Birth.year'] == primeiro_ano]['DEP_raw_MAT'].mean()
    base_ppd = df_res[df_res['Birth.year'] == primeiro_ano]['DEP_raw_PPD'].mean()

    df_res['DEP_PD'] = df_res['DEP_raw_DIR'] - (base_dir if not np.isnan(base_dir) else 0)
    df_res['DEP_MAT_PD'] = df_res['DEP_raw_MAT'] - (base_mat if not np.isnan(base_mat) else 0)
    df_res['DEP_PPD'] = df_res['DEP_raw_PPD'] - (base_ppd if not np.isnan(base_ppd) else 0)

    df_res['Acuracia_DIR_PD'] = acu_dir_pd
    df_res['Acuracia_MAT_PD'] = acu_mat_pd
    df_res['Acuracia_PPD'] = acu_ppd

    # Índice de Seleção e Ajuste de Base
    df_res['Indice_bruto'] = 100 + (0.25 * df_res['DEP_PD']) + (0.25 * df_res['DEP_MAT_PD']) + (0.50 * df_res['DEP_PPD'])
    base_indice = df_res[df_res['Birth.year'] == primeiro_ano]['Indice_bruto'].mean()
    df_res['Indice'] = df_res['Indice_bruto'] - (base_indice if not np.isnan(base_indice) else 0) + 100

    # Percentis exatos (Top %)
    df_res['Perc_Indice'] = calcular_percentil_exato(df_res['Indice'])
    df_res['Perc_DEP_PD'] = calcular_percentil_exato(df_res['DEP_PD'])
    df_res['Perc_DEP_MAT_PD'] = calcular_percentil_exato(df_res['DEP_MAT_PD'])
    df_res['Perc_DEP_PPD'] = calcular_percentil_exato(df_res['DEP_PPD'])

    return df_res