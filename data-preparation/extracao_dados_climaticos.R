pkgs <- c("nasapower","geobr","sf","dplyr","lubridate","arrow","purrr","readr","tibble","tidyr")
to_install <- pkgs[!sapply(pkgs, requireNamespace, quietly = TRUE)]
if (length(to_install)) install.packages(to_install)

library(nasapower)
library(geobr)
library(sf)
library(dplyr)
library(lubridate)
library(arrow)
library(purrr)
library(readr)
library(tibble)
library(tidyr)

data_inicial <- "2000-01-01"
data_final   <- "2023-12-31"

pausa_base <- 1.5   # pausa entre chamadas para evitar "Too many requests"
tentativas <- 3     # número de tentativas caso acabe dando erro de rede

ufs <- c("AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS","MT",
         "PA","PB","PE","PI","PR","RJ","RN","RO","RR","RS","SC","SE","SP","TO")

variaveis_power <- c("ALLSKY_SFC_UV_INDEX","T2M")  # UV + temperatura média 2m

dir.create("cache_power_uf", showWarnings = FALSE)  # cache por UF (Parquet)

obter_centroide_uf <- function(sigla_uf) {
  uf_poly <- geobr::read_state(code_state = sigla_uf, year = 2020, simplified = TRUE) |>
    sf::st_make_valid() |>
    sf::st_transform(4326)

  uf_proj <- sf::st_transform(uf_poly, 5880)
  centro_proj <- sf::st_centroid(uf_proj$geom)
  centro_wgs  <- sf::st_transform(centro_proj, 4326)
  coords <- sf::st_coordinates(centro_wgs)[1, ]
  list(lon = as.numeric(coords["X"]), lat = as.numeric(coords["Y"]))
}

parse_ano_mes_power <- function(df) {
  nms <- names(df)
  cand_year <- c("YEAR","Year","ANO","year")
  cand_mon  <- c("MO","MM","MONTH","Month","month","MES","Mes","MON","Mon","mon")

  col_year <- intersect(nms, cand_year)
  col_mon  <- intersect(nms, cand_mon)

  if (length(col_year) >= 1 && length(col_mon) >= 1) {
    return(df |>
      rename(ano = all_of(col_year[1]), mes = all_of(col_mon[1])) |>
      mutate(ano = as.integer(ano), mes = as.integer(as.character(mes))))
  }

  if ("YYYYMM" %in% nms) {
    return(df |>
      mutate(YYYYMM = as.integer(YYYYMM),
             ano = YYYYMM %/% 100L,
             mes = YYYYMM %%  100L))
  }

  if ("DATE" %in% nms) {
    return(df |>
      mutate(ano = year(as.Date(DATE)), mes = month(as.Date(DATE))))
  }
  if ("YYYYMMDD" %in% nms) {
    return(df |>
      mutate(ano = year(as.Date(YYYYMMDD, "%Y%m%d")),
             mes = month(as.Date(YYYYMMDD, "%Y%m%d"))))
  }

  # Formato YEAR + VAR_JAN..DEC → pivot
  meses_abbr <- toupper(month.abb)
  padroes <- unlist(lapply(variaveis_power, function(v) paste0("^", v, "_(", paste(meses_abbr, collapse="|"), ")$")))
  cols_mes <- grep(paste(padroes, collapse="|"), nms, value = TRUE)

  if ("YEAR" %in% nms && length(cols_mes) > 0) {
    return(df |>
      rename(ano = YEAR) |>
      pivot_longer(all_of(cols_mes), names_to = "var_mes", values_to = "valor") |>
      separate(var_mes, into = c("variavel","MES_ABBR"), sep = "_", extra = "merge") |>
      mutate(mes = match(toupper(MES_ABBR), meses_abbr)) |>
      pivot_wider(names_from = variavel, values_from = valor) |>
      select(ano, mes, all_of(variaveis_power)) |>
      arrange(ano, mes))
  }

  stop("NASA POWER mensal: não encontrei colunas de ano/mês esperadas.")
}

baixar_mensal_power_flex <- function(lon, lat, dt_ini, dt_fim, vars,
                                     pausa = pausa_base, tries = tentativas) {
  # 1) Tenta mensal
  tentativa <- 1
  repeat {
    resp <- try({
      nasapower::get_power(community="AG", pars=vars, temporal_api="monthly",
                           lonlat=c(lon, lat), dates=c(dt_ini, dt_fim))
    }, silent = TRUE)

    if (!inherits(resp, "try-error")) {
      df <- as_tibble(resp)
      parsed <- try(parse_ano_mes_power(df), silent = TRUE)
      if (!inherits(parsed, "try-error") && length(setdiff(vars, names(parsed))) == 0) {
        Sys.sleep(pausa)
        return(parsed |> select(ano, mes, all_of(vars)) |> arrange(ano, mes))
      }
      break
    }
    if (tentativa >= tries) break
    Sys.sleep(pausa * tentativa); tentativa <- tentativa + 1
  }

  # 2) Fallback: diário por ano + agrega para mensal (média)
  anos <- seq(as.integer(substr(dt_ini,1,4)), as.integer(substr(dt_fim,1,4)))
  lista_anos <- list()

  for (yy in anos) {
    ini_y <- max(as.Date(sprintf("%d-01-01", yy)), as.Date(dt_ini))
    fim_y <- min(as.Date(sprintf("%d-12-31", yy)), as.Date(dt_fim))
    if (ini_y > fim_y) next

    tentativa <- 1
    repeat {
      resp_d <- try({
        nasapower::get_power(community="AG", pars=vars, temporal_api="daily",
                             lonlat=c(lon, lat), dates=c(as.character(ini_y), as.character(fim_y)))
      }, silent = TRUE)

      if (!inherits(resp_d, "try-error")) {
        dfd <- as_tibble(resp_d)
        if ("DATE" %in% names(dfd)) dfd <- dfd |> mutate(data = as.Date(DATE))
        else if ("YYYYMMDD" %in% names(dfd)) dfd <- dfd |> mutate(data = as.Date(YYYYMMDD, "%Y%m%d"))
        else stop("POWER diário: coluna de data ausente (DATE/ YYYYMMDD).")

        stopifnot(length(setdiff(vars, names(dfd))) == 0)

        dfd_m <- dfd |>
          mutate(ano = year(data), mes = month(data)) |>
          group_by(ano, mes) |>
          summarise(across(all_of(vars), ~ mean(.x, na.rm = TRUE)), .groups = "drop") |>
          arrange(ano, mes)

        lista_anos[[as.character(yy)]] <- dfd_m
        Sys.sleep(pausa); break
      }
      if (tentativa >= tries) stop(sprintf("Fallback diário falhou no ano %d.", yy))
      Sys.sleep(pausa * tentativa); tentativa <- tentativa + 1
    }
  }
  bind_rows(lista_anos)
}

construir_uf_mensal_centroide <- function(sigla_uf) {
  message("Processando UF: ", sigla_uf, " | Período: ", data_inicial, " a ", data_final)

  cache_path <- file.path("cache_power_uf",
                          sprintf("POWER_%s_%s_%s.parquet", sigla_uf, data_inicial, data_final))

  if (file.exists(cache_path)) {
    df <- read_parquet(cache_path)  # reaproveita se já baixou
  } else {
    ctd <- obter_centroide_uf(sigla_uf)
    df <- baixar_mensal_power_flex(ctd$lon, ctd$lat, data_inicial, data_final,
                                   variaveis_power, pausa = pausa_base, tries = tentativas)
    write_parquet(df, cache_path, compression = "zstd")
  }

  df |>
    mutate(uf = sigla_uf) |>
    relocate(uf, ano, mes) |>
    rename(indice_uv = ALLSKY_SFC_UV_INDEX,
           temperatura_media_2m = T2M)
}

safe_build <- purrr::safely(construir_uf_mensal_centroide, otherwise = NULL)

res_list <- purrr::map(ufs, safe_build)
ok   <- purrr::map(res_list, "result")
errs <- purrr::map(res_list, "error")

ufs_ok   <- ufs[ purrr::map_lgl(ok,   ~ !is.null(.x)) ]
ufs_fail <- ufs[ purrr::map_lgl(errs, ~ !is.null(.x)) ]

message("UFs concluídas: ", paste(ufs_ok, collapse=", "))
if (length(ufs_fail) > 0) {
  message("UFs que falharam: ", paste(ufs_fail, collapse=", "))
  message("Dica: rode novamente; o cache mantém as UFs já concluídas.")
}

resultado <- dplyr::bind_rows(purrr::compact(ok))

# Converte NaN do índice UV (quando o POWER não retorna valor) para NA
resultado <- resultado |>
  mutate(indice_uv = ifelse(is.nan(indice_uv), NA_real_, indice_uv))

# Salva em Parquet
arrow::write_parquet(
  resultado,
  "nasa_power_uf_mensal_2000_2023_ptbr_centroide.parquet",
  compression = "zstd"
)

# Salva em CSV, segundo opcao pensando em inputar esses dados no MySQL
readr::write_csv(
  resultado,
  "nasa_power_uf_mensal_2000_2023_ptbr_centroide.csv"
)


