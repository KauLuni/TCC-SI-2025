packages <- c("readr","dplyr","tidyr","stringr","lubridate","janitor","purrr")
install_if_missing <- function(pk) if(!requireNamespace(pk, quietly = TRUE)) install.packages(pk)
invisible(lapply(packages, install_if_missing))

library(readr); library(dplyr); library(tidyr); library(stringr)
library(lubridate); library(janitor); library(purrr)

path_incid <- "cancer_pele_unificado.csv"
path_clima <- "nasa_power_uf_mensal_2000_2023_ptbr_centroide.csv"

desktop_dir <- file.path(Sys.getenv("USERPROFILE"), "Desktop")
if (!dir.exists(desktop_dir)) dir.create(desktop_dir, recursive = TRUE, showWarnings = FALSE)
path_out <- file.path(desktop_dir, "incidencia_clima_unificado_2000_2023.csv")

incid_raw <- readr::read_csv(path_incid, locale = locale(encoding = "UTF-8"), show_col_types = FALSE)
incid <- incid_raw %>% janitor::clean_names()

incid <- incid %>%
  mutate(
    uf  = case_when(
      "uf"     %in% names(.) & !is.na(uf)    ~ as.character(uf),
      "uf_zi"  %in% names(.) & !is.na(uf_zi) ~ as.character(uf_zi),
      TRUE ~ NA_character_
    ),
    ano = dplyr::coalesce(.data$ano, .data$ano_cmpt),
    mes = if ("mes_cmpt" %in% names(.)) .data$mes_cmpt else NA_integer_
  ) %>%
  mutate(
    uf  = toupper(as.character(uf)),
    ano = as.integer(ano),
    mes = as.integer(mes)
  ) %>%
  filter(!is.na(ano), ano >= 2000, ano <= 2023)

if ("UF" %in% names(incid_raw)) {
  incid$uf <- toupper(as.character(incid_raw$UF))
}

incid <- incid %>%
  arrange(ano, mes, uf) %>%
  mutate(id_caso = dplyr::row_number())

clima <- readr::read_csv(path_clima, locale = locale(encoding = "UTF-8"), show_col_types = FALSE) %>%
  janitor::clean_names() %>%
  mutate(
    uf  = toupper(as.character(uf)),
    ano = as.integer(ano),
    mes = as.integer(mes)
  ) %>%
  filter(!is.na(uf), !is.na(ano), ano >= 2000, ano <= 2023)

num_cols <- intersect(c("indice_uv","temperatura_media_2m"), names(clima))
for (cc in num_cols) {
  if (is.character(clima[[cc]])) {
    v <- readr::parse_number(clima[[cc]], locale = locale(decimal_mark = ".", grouping_mark = ","))
    if (all(is.na(v))) v <- readr::parse_number(clima[[cc]], locale = locale(decimal_mark = ",", grouping_mark = "."))
    clima[[cc]] <- v
  } else {
    clima[[cc]] <- as.numeric(clima[[cc]])
  }
  clima[[cc]] <- round(clima[[cc]], 2)
}

tem_mes_incid <- incid %>% summarise(tem = any(!is.na(mes) & dplyr::between(mes, 1L, 12L))) %>% pull(tem)

if (isTRUE(tem_mes_incid)) {
  incid_com_mes <- incid %>% filter(!is.na(mes) & dplyr::between(mes, 1L, 12L))
  incid_sem_mes <- incid %>% filter(is.na(mes) | !dplyr::between(mes, 1L, 12L))

  unificado_com_mes <- incid_com_mes %>%
    left_join(clima, by = c("uf" = "uf", "ano" = "ano", "mes" = "mes"))

  clima_anual <- clima %>%
    group_by(uf, ano) %>%
    summarise(
      indice_uv = round(mean(indice_uv, na.rm = TRUE), 2),
      temperatura_media_2m = round(mean(temperatura_media_2m, na.rm = TRUE), 2),
      .groups = "drop"
    )

  unificado_sem_mes <- incid_sem_mes %>%
    left_join(clima_anual, by = c("uf" = "uf", "ano" = "ano"))

  unificado <- dplyr::bind_rows(unificado_com_mes, unificado_sem_mes) %>%
    arrange(ano, mes, uf, id_caso)
} else {
  clima_anual <- clima %>%
    group_by(uf, ano) %>%
    summarise(
      indice_uv = round(mean(indice_uv, na.rm = TRUE), 2),
      temperatura_media_2m = round(mean(temperatura_media_2m, na.rm = TRUE), 2),
      .groups = "drop"
    )

  unificado <- incid %>%
    left_join(clima_anual, by = c("uf" = "uf", "ano" = "ano")) %>%
    arrange(ano, uf, id_caso)
}

if ("indice_uv" %in% names(unificado))            unificado$indice_uv            <- round(unificado$indice_uv, 2)
if ("temperatura_media_2m" %in% names(unificado)) unificado$temperatura_media_2m <- round(unificado$temperatura_media_2m, 2)

readr::write_csv2(unificado, file = path_out, na = "") #exportação para excel

# Contagem de linhas
cat("Incidência:", nrow(incid), " | Clima:", nrow(clima), "\n",
    "Unificado:", nrow(unificado), "\n")

# NAs nas variáveis climáticas
unificado %>%
  summarise(
    n_na_indice_uv = sum(is.na(indice_uv)),
    n_na_temp2m    = sum(is.na(temperatura_media_2m))
  ) %>% print()

