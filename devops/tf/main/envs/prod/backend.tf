terraform {
  backend "s3" {
    bucket = "bittensor_sentinel-awgkkh"
    key    = "prod/main.tfstate"
    region = "us-east-1"
  }
}
