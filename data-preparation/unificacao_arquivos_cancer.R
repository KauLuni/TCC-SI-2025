library(arrow)
library(dplyr)
library(stringr)

# Define a pasta de entrada
# Essa é a pasta onde estão os arquivos .parquet filtrados por estado e ano
pasta_entrada <- "dados_parquet/"

# Cria a pasta de saída (se ainda não existir)
# Essa será a pasta onde o arquivo final unificado será salvo
pasta_saida <- "dados_unificado/"
dir.create(pasta_saida, showWarnings = FALSE)  # Não gera erro se a pasta já existir

# Lista todos os arquivos .parquet da pasta de entrada
# permite iterar (fazer loop) por todos os arquivos filtrados
arquivos <- list.files(
  path = pasta_entrada,             
  pattern = "\\.parquet$",          
  full.names = TRUE                 
)

# Inicializa uma lista vazia para armazenar os dados que vamos ler
dados_lista <- list()

#  Loop por todos os arquivos encontrados
for (arquivo in arquivos) {
  # Mostra qual arquivo está sendo lido (apenas para acompanhamento)
  cat("Lendo:", arquivo, "\n")

  # Lê o conteúdo do arquivo parquet
  df <- read_parquet(arquivo)

  # Extrai o estado (UF) e o ano do nome do arquivo usando regex
  # Exemplo: "cancer_pele_SP_2020.parquet" → UF = "SP", ano = 2020
  partes <- unlist(stringr::str_match(arquivo, "cancer_pele_([A-Z]{2})_(\\d{4})"))
  uf <- partes[2]              # Estado
  ano <- as.integer(partes[3]) # Ano (em número)

  # Adiciona essas informações como novas colunas no dataframe
  df$UF <- uf
  df$ANO <- ano

  dados_lista[[length(dados_lista) + 1]] <- df
}

# Concatena (empilha) todos os dataframes da lista em um único
df_unificado <- bind_rows(dados_lista)

# Define o nome do arquivo final unificado
arquivo_final <- file.path(pasta_saida, "cancer_pele_unificado.parquet")

# Salva o dataframe unificado em formato .parquet, pois é leve e otimizado (os volumes de dados são BEEEM grandes)
write_parquet(df_unificado, arquivo_final)

cat("Arquivo unificado salvo em:", arquivo_final, "\n")
