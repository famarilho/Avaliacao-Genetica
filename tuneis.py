from pyngrok import ngrok
import time

# Abre o túnel público para a porta local 8000 (onde o FastAPI roda)
public_url = ngrok.connect(8000)

print("\n" + "="*60)
print("🚀 TÚNEL PÚBLICO CRIADO COM SUCESSO!")
print(f"URL pública da sua API: {public_url}/avaliar")
print("="*60 + "\n")

# Mantém o túnel ativo enquanto o script estiver a rodar
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Túnel encerrado.")