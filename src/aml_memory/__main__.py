import uvicorn


if __name__ == "__main__":
    uvicorn.run("aml_memory.api:app", host="0.0.0.0", port=8080)

