package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/gorilla/websocket"
	"github.com/mmcdole/gofeed"
	"github.com/segmentio/kafka-go"
)

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
	}

	newsWriter = &kafka.Writer{
		Addr:                   kafka.TCP(broker),
		Topic:                  "financial_news",
		Balancer:               &kafka.LeastBytes{},
		AllowAutoTopicCreation: true,
		MaxAttempts:            5,
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
	log.Println("Start Binance WS")

	wsUrl := "wss://stream.binance.com:9443/ws/btcusdt@trade/ethusdt@trade"

	conn, _, err := websocket.DefaultDialer.Dial(wsUrl, nil)

	if err != nil {
		log.Fatal("Binance WS Dial Error: ", err)
	}
	defer conn.Close()

	for {
		_, message, err := conn.ReadMessage()

		if err != nil {
			log.Println("Binance Read Error:", err)
			return
		}

		var rawJson map[string]interface{}
		json.Unmarshal(message, &rawJson)

		// log.Println(rawJson)

		// unix epoch float64 miliseconds to iso-8601 datetime string, with milliseconds
		datetime := time.Unix(0, int64(rawJson["E"].(float64))*int64(time.Millisecond)).UTC().Format("2006-01-02T15:04:05.000Z07:00")

		// strings to floats
		var price, volume float64
		fmt.Sscanf(rawJson["p"].(string), "%f", &price)
		fmt.Sscanf(rawJson["q"].(string), "%f", &volume)

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

func startNewsScraper() {
	log.Println("Start News Scraper")

	feedParser := gofeed.NewParser()
	readUrls := map[string]bool{}

	for {
		feed, err := feedParser.ParseURL("https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL,MSFT,TSLA,BTC-USD")

		if err != nil {
			log.Println("RSS parsing error: ", err)
		} else {
			for _, item := range feed.Items {
				if !readUrls[item.Link] {
					readUrls[item.Link] = true

					publishDate := item.PublishedParsed
					if publishDate == nil {
						now := time.Now()
						publishDate = &now
					}

					publishedAt := publishDate.UTC().Format(time.RFC3339)

					newsObject := NewsObject{
						PublishedAt: publishedAt,
						Headline:    item.Title,
						Summary:     item.Description,
						URL:         item.Link,
						Tickers:     []string{},
					}

					// log.Println(newsObject)
					pushToKafka(newsWriter, "", newsObject)
				}
			}
		}

		time.Sleep(3 * time.Minute)
	}
}

func main() {
	fmt.Println("Starting Data Ingestion")

	fmt.Println("Initializing Kafka Writers, a few errors may appear because topic is in the process of creation")
	initKafkaWriters()

	go startBinanceWS()
	go startNewsScraper()

	select {}
}
