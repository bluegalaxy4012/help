package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/Finnhub-Stock-API/finnhub-go/v2"
	"github.com/gorilla/websocket"
	"github.com/segmentio/kafka-go"
)

// ---------------------------------------------
// THE ASSETS THAT THE MODEL WILL BE AWARE OF
// ---------------------------------------------

var TopCryptos = []string{
	"BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX",
	"AVAX", "DOT", "LINK", "SHIB", "BCH", "LTC", "NEAR",
}

var TopStocks = []string{
	"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "TSM",
	"LLY", "V", "WMT", "JPM", "AVGO", "NVO", "JNJ",
}

var TopETFs = []string{
	"SPY", "VT", "QQQ", "IWM", "GLD", "SLV", "USO", "UNG", "TLT",
	"IBIT", "ETHA", "XLF", "XLK", "XLE", "XLV", "VNQ",
}

var pricesWriter *kafka.Writer
var newsWriter *kafka.Writer

type PriceObject struct {
	Time   string  `json:"time"`
	Symbol string  `json:"symbol"`
	Price  float64 `json:"price"`
	Volume float64 `json:"volume"`
}

type NewsObject struct {
	PublishedAt string   `json:"published_at"`
	Headline    string   `json:"headline"`
	Summary     string   `json:"summary"`
	URL         string   `json:"url"`
	Tickers     []string `json:"tickers"`
}

func initKafkaWriters() {
	broker := os.Getenv("KAFKA_BROKER")
	if broker == "" {
		broker = "localhost:9092"
	}

	pricesWriter = &kafka.Writer{
		Addr:                   kafka.TCP(broker),
		Topic:                  "raw_prices",
		Balancer:               &kafka.LeastBytes{},
		AllowAutoTopicCreation: true,
		MaxAttempts:            5,
		Async:                  true,
		BatchSize:              100,
		BatchTimeout:           10 * time.Millisecond,
	}

	newsWriter = &kafka.Writer{
		Addr:                   kafka.TCP(broker),
		Topic:                  "financial_news",
		Balancer:               &kafka.LeastBytes{},
		AllowAutoTopicCreation: true,
		MaxAttempts:            5,
		Async:                  true,
		BatchSize:              20,
		BatchTimeout:           20 * time.Millisecond,
	}
}

func pushToKafka(writer *kafka.Writer, key string, value interface{}) {
	// kafkaWriter := &kafka.Writer{
	// 	Addr:     kafka.TCP("localhost:9092"),
	// 	Topic:    topic,
	// 	Balancer: &kafka.LeastBytes{},
	// }
	// defer kafkaWriter.Close()

	message, err := json.Marshal(value)

	if err != nil {
		log.Println("Failed to format JSON: ", err)
		return
	}

	err = writer.WriteMessages(
		context.Background(),
		kafka.Message{
			Key:   []byte(key),
			Value: message,
		},
	)

	if err != nil {
		log.Println("Failed to push to Kafka: ", err)
		return
	}
}

func startBinanceWS() {
	log.Println("Start Binance WS for Cryptos")

	var streams []string
	for _, crypto := range TopCryptos {
		streams = append(streams, strings.ToLower(crypto)+"usdt@trade") // binance format
	}

	wsUrl := "wss://stream.binance.com:9443/ws/" + strings.Join(streams, "/")

	for {
		conn, _, err := websocket.DefaultDialer.Dial(wsUrl, nil)
		if err != nil {
			log.Println("Binance WS Dial Error: ", err)
			time.Sleep(6 * time.Second)
			continue
		}

		for {
			_, message, err := conn.ReadMessage()

			if err != nil {
				log.Println("Binance Read Error:", err)
				conn.Close()
				break
			}

			var rawJson map[string]interface{}
			json.Unmarshal(message, &rawJson)

			// log.Println(rawJson)
			if eType, ok := rawJson["e"].(string); !ok || eType != "trade" {
				continue
			}

			// unix epoch float64 miliseconds to iso-8601 datetime string, with milliseconds
			datetime := time.Unix(0, int64(rawJson["E"].(float64))*int64(time.Millisecond)).UTC().Format("2006-01-02T15:04:05.000Z07:00")

			// strings to floats
			var price, volume float64
			// fmt.Sscanf(rawJson["p"].(string), "%f", &price)
			// fmt.Sscanf(rawJson["q"].(string), "%f", &volume)
			price, err1 := strconv.ParseFloat(rawJson["p"].(string), 64)
			volume, err2 := strconv.ParseFloat(rawJson["q"].(string), 64)

			if err1 != nil || err2 != nil {
				continue
			}

			var symbol string
			symbol = rawJson["s"].(string)

			priceObject := PriceObject{
				Time:   datetime,
				Symbol: symbol,
				Price:  price,
				Volume: volume,
			}

			// log.Println(priceObject)
			pushToKafka(pricesWriter, symbol, priceObject)
		}

	}
}

func startFinnhubWS() {
	log.Println("Start Finnhub WS for Stocks and ETFs")

	apiKey := os.Getenv("FINNHUB_API_KEY")
	url := fmt.Sprintf("wss://ws.finnhub.io?token=%s", apiKey)

	allEquities := append(TopStocks, TopETFs...)

	for {
		conn, _, err := websocket.DefaultDialer.Dial(url, nil)
		if err != nil {
			log.Println("Finnhub WS dial error: ", err)
			time.Sleep(6 * time.Second)
			continue
		}

		for _, t := range allEquities {
			subMsg := fmt.Sprintf(`{"type":"subscribe","symbol":"%s"}`, t)
			conn.WriteMessage(websocket.TextMessage, []byte(subMsg))
		}

		for {
			_, message, err := conn.ReadMessage()
			if err != nil {
				log.Println("Finnhub WS read error: ", err)
				conn.Close()
				break
			}

			var rawJson map[string]interface{}
			json.Unmarshal(message, &rawJson)

			if data, ok := rawJson["data"].([]interface{}); ok {
				for _, item := range data {
					trade := item.(map[string]interface{})
					// datetime := time.UnixMilli(int64(trade["t"].(float64))).UTC().Format("2006-01-02T15:04:05.000Z07:00")
					datetime := time.Unix(0, int64(trade["t"].(float64))*int64(time.Millisecond)).UTC().Format("2006-01-02T15:04:05.000Z07:00")

					pushToKafka(pricesWriter, trade["s"].(string), PriceObject{
						Time:   datetime,
						Symbol: trade["s"].(string),
						Price:  trade["p"].(float64),
						Volume: trade["v"].(float64),
					})
				}
			}

		}

	}

}

func startNewsScraper() {
	log.Println("Start News Scraper")

	apiKey := os.Getenv("FINNHUB_API_KEY")

	cfg := finnhub.NewConfiguration()
	cfg.AddDefaultHeader("X-Finnhub-Token", apiKey)
	finnhubClient := finnhub.NewAPIClient(cfg)

	tickers := append(TopStocks, TopETFs...)
	readUrls := map[string]bool{}

	for {
		today := time.Now().UTC().Format("2006-01-02")

		for _, ticker := range tickers {
			news, _, err := finnhubClient.DefaultApi.CompanyNews(context.Background()).Symbol(ticker).From(today).To(today).Execute()

			if err != nil {
				// log.Printf("Finnhub SDK error for %s: %v", ticker, err)
				continue
			}

			for _, item := range news {
				newsUrl := item.GetUrl()

				if !readUrls[newsUrl] {
					readUrls[newsUrl] = true

					unixTime := item.GetDatetime()
					publishedAt := time.Unix(unixTime, 0).UTC().Format(time.RFC3339)

					newsObject := NewsObject{
						PublishedAt: publishedAt,
						Headline:    item.GetHeadline(),
						Summary:     item.GetSummary(),
						URL:         newsUrl,
						Tickers:     []string{ticker},
					}

					// log.Println(newsObject)
					pushToKafka(newsWriter, "", newsObject)
				}
			}

			time.Sleep(500 * time.Millisecond)
		}

		time.Sleep(5 * time.Minute)
	}
}

func main() {
	fmt.Println("Starting Data Ingestion")

	fmt.Println("Initializing Kafka Writers, a few errors may appear because topic is in the process of creation")
	initKafkaWriters()

	go startBinanceWS()
	go startFinnhubWS()
	go startNewsScraper()

	select {}
}
