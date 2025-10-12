# SCRIPT RESPONSÁVEL PELA PROJEÇÃO UTILIZANDO OS MODELOS PREDITIVOS PROPHET, ARIMA E ETS

# Pacotes utilizados
packages <- c("readr", "dplyr", "ggplot2", "forecast", "prophet", "scales", "lubridate")

# Instalar se não estiverem presentes
install_if_missing <- function(pk) if(!requireNamespace(pk, quietly = TRUE)) install.packages(pk)
invisible(lapply(packages, install_if_missing))

library(readr)
library(dplyr)
library(ggplot2)
library(forecast)
library(prophet)
library(scales)
library(lubridate)

# Leitura do arquivo CSV gerado anteriormente
df <- read_csv("dados_unificado/cancer_pele_unificado.csv")

# Agrupa por ano para obter total de casos anuais
df_ano <- df %>%
  group_by(ANO) %>%
  summarise(cases = n()) %>%
  rename(year = ANO) %>%
  arrange(year)

# Cria uma série temporal anual
ts_data <- ts(df_ano$cases, start = min(df_ano$year), frequency = 1)

# Ajustar modelo ARIMA automaticamente
fit_arima <- auto.arima(ts_data)

# Previsão para os próximos 10 anos
forecast_arima <- forecast(fit_arima, h = 10)

autoplot(forecast_arima) +
  labs(title = "Previsão de Câncer de Pele - Modelo ARIMA",
       x = "Ano",
       y = "Casos Estimados") +
  theme_minimal() +
  scale_y_continuous(labels = comma_format(big.mark = ".", decimal.mark = ",")) +
  theme(plot.title = element_text(hjust = 0.5))

  # Ajustar modelo ETS (suavização exponencial)
fit_ets <- ets(ts_data)

# Previsão
forecast_ets <- forecast(fit_ets, h = 10)

# Gráfico
autoplot(forecast_ets) +
  labs(title = "Previsão de Câncer de Pele - Modelo ETS",
       x = "Ano",
       y = "Casos Estimados") +
  theme_minimal() +
  scale_y_continuous(labels = comma_format(big.mark = ".", decimal.mark = ",")) +
  theme(plot.title = element_text(hjust = 0.5))

# Preparar dados no formato Prophet (mais leve, pois a princípio utilizariamos as ferramentas: S3 e QuickSight da AWS)
prophet_df <- df_ano %>%
  mutate(ds = as.Date(paste0(year, "-01-01")),
         y = cases) %>%
  select(ds, y)

# Ajustar o modelo
modelo_prophet <- prophet(prophet_df)

# Cria datas futuras
future <- make_future_dataframe(modelo_prophet, periods = 10, freq = "year")

# Previsão
forecast_prophet <- predict(modelo_prophet, future)

# Gráfico geral
plot(modelo_prophet, forecast_prophet) +
  labs(title = "Previsão de Câncer de Pele - Modelo Prophet",
       x = "Ano",
       y = "Casos Estimados")

# Gráfico de componentes
prophet_plot_components(modelo_prophet, forecast_prophet)

# Previsão ARIMA
out_arima <- data.frame(
  year = (max(df_ano$year)+1):(max(df_ano$year)+10),
  model = "ARIMA",
  point = as.numeric(forecast_arima$mean),
  lo80 = as.numeric(forecast_arima$lower[ ,1]),
  hi80 = as.numeric(forecast_arima$upper[ ,1]),
  lo95 = as.numeric(forecast_arima$lower[ ,2]),
  hi95 = as.numeric(forecast_arima$upper[ ,2])
)

# Previsão ETS
out_ets <- data.frame(
  year = (max(df_ano$year)+1):(max(df_ano$year)+10),
  model = "ETS",
  point = as.numeric(forecast_ets$mean),
  lo80 = as.numeric(forecast_ets$lower[ ,1]),
  hi80 = as.numeric(forecast_ets$upper[ ,1]),
  lo95 = as.numeric(forecast_ets$lower[ ,2]),
  hi95 = as.numeric(forecast_ets$upper[ ,2])
)

# Previsão Prophet
out_prophet <- forecast_prophet %>%
  filter(ds > max(prophet_df$ds)) %>%
  transmute(
    year = year(ds),
    model = "Prophet",
    point = yhat,
    lo80 = yhat_lower,
    hi80 = yhat_upper,
    lo95 = NA,
    hi95 = NA
  )

# Unificar e salvar
previsoes_final <- bind_rows(out_arima, out_ets, out_prophet) %>% arrange(model, year)
write_csv(previsoes_final, "resultados/previsoes_cancer_pele.csv")