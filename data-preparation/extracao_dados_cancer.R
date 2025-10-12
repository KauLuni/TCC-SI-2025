# SCRIPT PARA A EXTRAÇÃO DOS DADOS HOMOLOGADOS PELO SUS UTILIZANDO O PACOTE MICRODATASUS
install.packages("microdatasus"install.packages("arrow"))

library(microdatasus)  
library(dplyr)         
library(arrow)         #

ufs <- c("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
         "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
         "RO", "RR", "RS", "SC", "SE", "SP", "TO")

# Intervalo de anos que serão analisados
anos <- 2000:2023

# loop principal para baixar, processar e salvar os dados de cada estado e ano
for (uf in ufs) {
  for (ano in anos) {
    message("Baixando: ", uf, " - ", ano)

    try({
        # função para baixar os dados hospitalares mensais (.dbc) do SIH/SUS, diretamente do FTP do DataSUS.
        dados_brutos <- fetch_datasus(
        year_start = ano,
        year_end = ano,
        month_start = 1,
        month_end = 12,
        uf = uf,
        information_system = "SIH-RD"
      )
        dados_proc <- process_sih(dados_brutos)
        cancer_pele <- subset(
            dados_proc,
            substr(DIAG_PRINC, 1, 3) %in% c("C43", "C44")
      )
      		  nome_arquivo <- paste0("cancer_pele_", uf, "_", ano, ".parquet")
      write_parquet(cancer_pele, nome_arquivo)
        }, silent = TRUE) # serve para que se ocorrer algum erro como dados ausentes ele ignora erro e segue
  }
}