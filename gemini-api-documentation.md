Starting with the Gemini 2.0 release in late 2024, we introduced a new set of
libraries called the [Google GenAI SDK](https://ai.google.dev/gemini-api/docs/libraries). It offers
an improved developer experience through
an [updated client architecture](https://ai.google.dev/gemini-api/docs/migrate#client), and
[simplifies the transition](https://ai.google.dev/gemini-api/docs/migrate-to-cloud) between developer
and enterprise workflows.

The Google GenAI SDK is now in [General Availability (GA)](https://ai.google.dev/gemini-api/docs/libraries#new-libraries) across all supported
platforms. If you're using one of our [legacy libraries](https://ai.google.dev/gemini-api/docs/libraries#previous-sdks), we strongly recommend you to
migrate.

This guide provides before-and-after examples of migrated code to help you get
started.
| **Note:** The Go examples omit imports and other boilerplate code to improve readability.

## Installation

**Before**  

### Python

    pip install -U -q "google-generativeai"

### JavaScript

    npm install @google/generative-ai

### Go

    go get github.com/google/generative-ai-go

**After**  

### Python

    pip install -U -q "google-genai"

### JavaScript

    npm install @google/genai

### Go

    go get google.golang.org/genai

## API access

The old SDK implicitly handled the API client behind the scenes using a variety
of ad hoc methods. This made it hard to manage the client and credentials.
Now, you interact through a central `Client` object. This `Client` object acts
as a single entry point for various API services (e.g., `models`, `chats`,
`files`, `tunings`), promoting consistency and simplifying credential and
configuration management across different API calls.

**Before (Less Centralized API Access)**  

### Python

The old SDK didn't explicitly use a top-level client object for most API
calls. You would directly instantiate and interact with `GenerativeModel`
objects.  

    import google.generativeai as genai

    # Directly create and use model objects
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(...)
    chat = model.start_chat(...)

### JavaScript

While `GoogleGenerativeAI` was a central point for models and chat, other
functionalities like file and cache management often required importing and
instantiating entirely separate client classes.  

    import { GoogleGenerativeAI } from "@google/generative-ai";
    import { GoogleAIFileManager, GoogleAICacheManager } from "@google/generative-ai/server"; // For files/caching

    const genAI = new GoogleGenerativeAI("YOUR_API_KEY");
    const fileManager = new GoogleAIFileManager("YOUR_API_KEY");
    const cacheManager = new GoogleAICacheManager("YOUR_API_KEY");

    // Get a model instance, then call methods on it
    const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });
    const result = await model.generateContent(...);
    const chat = model.startChat(...);

    // Call methods on separate client objects for other services
    const uploadedFile = await fileManager.uploadFile(...);
    const cache = await cacheManager.create(...);

### Go

The `genai.NewClient` function created a client, but generative model
operations were typically called on a separate `GenerativeModel` instance
obtained from this client. Other services might have been accessed via
distinct packages or patterns.  

    import (
          "github.com/google/generative-ai-go/genai"
          "github.com/google/generative-ai-go/genai/fileman" // For files
          "google.golang.org/api/option"
    )

    client, err := genai.NewClient(ctx, option.WithAPIKey("YOUR_API_KEY"))
    fileClient, err := fileman.NewClient(ctx, option.WithAPIKey("YOUR_API_KEY"))

    // Get a model instance, then call methods on it
    model := client.GenerativeModel("gemini-1.5-flash")
    resp, err := model.GenerateContent(...)
    cs := model.StartChat()

    // Call methods on separate client objects for other services
    uploadedFile, err := fileClient.UploadFile(...)

**After (Centralized Client Object)**  

### Python

    from google import genai

    # Create a single client object
    client = genai.Client()

    # Access API methods through services on the client object
    response = client.models.generate_content(...)
    chat = client.chats.create(...)
    my_file = client.files.upload(...)
    tuning_job = client.tunings.tune(...)

### JavaScript

    import { GoogleGenAI } from "@google/genai";

    // Create a single client object
    const ai = new GoogleGenAI({apiKey: "YOUR_API_KEY"});

    // Access API methods through services on the client object
    const response = await ai.models.generateContent(...);
    const chat = ai.chats.create(...);
    const uploadedFile = await ai.files.upload(...);
    const cache = await ai.caches.create(...);

### Go

    import "google.golang.org/genai"

    // Create a single client object
    client, err := genai.NewClient(ctx, nil)

    // Access API methods through services on the client object
    result, err := client.Models.GenerateContent(...)
    chat, err := client.Chats.Create(...)
    uploadedFile, err := client.Files.Upload(...)
    tuningJob, err := client.Tunings.Tune(...)

## Authentication

Both legacy and new libraries authenticate using API keys. You can
[create](https://aistudio.google.com/app/apikey) your API key in Google AI
Studio.

**Before**  

### Python

The old SDK handled the API client object implicitly.  

    import google.generativeai as genai

    genai.configure(api_key=...)

### JavaScript

    import { GoogleGenerativeAI } from "@google/generative-ai";

    const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY");

### Go

Import the Google libraries:  

    import (
          "github.com/google/generative-ai-go/genai"
          "google.golang.org/api/option"
    )

Create the client:  

    client, err := genai.NewClient(ctx, option.WithAPIKey("GOOGLE_API_KEY"))

**After**  

### Python

With Google GenAI SDK, you create an API client first, which is used to call
the API.
The new SDK will pick up your API key from either one of the
`GEMINI_API_KEY` or `GOOGLE_API_KEY` environment variables, if you don't
pass one to the client.  

    export GEMINI_API_KEY="YOUR_API_KEY"

    from google import genai

    client = genai.Client() # Set the API key using the GEMINI_API_KEY env var.
                            # Alternatively, you could set the API key explicitly:
                            # client = genai.Client(api_key="your_api_key")

### JavaScript

    import { GoogleGenAI } from "@google/genai";

    const ai = new GoogleGenAI({apiKey: "GEMINI_API_KEY"});

### Go

Import the GenAI library:  

    import "google.golang.org/genai"

Create the client:  

    client, err := genai.NewClient(ctx, &genai.ClientConfig{
            Backend:  genai.BackendGeminiAPI,
    })

## Generate content

### Text

**Before**  

### Python

Previously, there were no client objects, you accessed APIs directly through
`GenerativeModel` objects.  

    import google.generativeai as genai

    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(
        'Tell me a story in 300 words'
    )
    print(response.text)

### JavaScript

    import { GoogleGenerativeAI } from "@google/generative-ai";

    const genAI = new GoogleGenerativeAI(process.env.API_KEY);
    const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });
    const prompt = "Tell me a story in 300 words";

    const result = await model.generateContent(prompt);
    console.log(result.response.text());

### Go

    ctx := context.Background()
    client, err := genai.NewClient(ctx, option.WithAPIKey("GOOGLE_API_KEY"))
    if err != nil {
        log.Fatal(err)
    }
    defer client.Close()

    model := client.GenerativeModel("gemini-1.5-flash")
    resp, err := model.GenerateContent(ctx, genai.Text("Tell me a story in 300 words."))
    if err != nil {
        log.Fatal(err)
    }

    printResponse(resp) // utility for printing response parts

**After**  

### Python

The new Google GenAI SDK provides access to all the API methods through the
`Client` object. Except for a few stateful special cases (`chat` and
live-api `session`s), these are all stateless functions. For utility and
uniformity, objects returned are `pydantic` classes.  

    from google import genai
    client = genai.Client()

    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents='Tell me a story in 300 words.'
    )
    print(response.text)

    print(response.model_dump_json(
        exclude_none=True, indent=4))

### JavaScript

    import { GoogleGenAI } from "@google/genai";

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });

    const response = await ai.models.generateContent({
      model: "gemini-2.0-flash",
      contents: "Tell me a story in 300 words.",
    });
    console.log(response.text);

### Go

    ctx := context.Background()
      client, err := genai.NewClient(ctx, nil)
    if err != nil {
        log.Fatal(err)
    }

    result, err := client.Models.GenerateContent(ctx, "gemini-2.0-flash", genai.Text("Tell me a story in 300 words."), nil)
    if err != nil {
        log.Fatal(err)
    }
    debugPrint(result) // utility for printing result

### Image

**Before**  

### Python

    import google.generativeai as genai

    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content([
        'Tell me a story based on this image',
        Image.open(image_path)
    ])
    print(response.text)

### JavaScript

    import { GoogleGenerativeAI } from "@google/generative-ai";

    const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY");
    const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });

    function fileToGenerativePart(path, mimeType) {
      return {
        inlineData: {
          data: Buffer.from(fs.readFileSync(path)).toString("base64"),
          mimeType,
        },
      };
    }

    const prompt = "Tell me a story based on this image";

    const imagePart = fileToGenerativePart(
      `path/to/organ.jpg`,
      "image/jpeg",
    );

    const result = await model.generateContent([prompt, imagePart]);
    console.log(result.response.text());

### Go

    ctx := context.Background()
    client, err := genai.NewClient(ctx, option.WithAPIKey("GOOGLE_API_KEY"))
    if err != nil {
        log.Fatal(err)
    }
    defer client.Close()

    model := client.GenerativeModel("gemini-1.5-flash")

    imgData, err := os.ReadFile("path/to/organ.jpg")
    if err != nil {
        log.Fatal(err)
    }

    resp, err := model.GenerateContent(ctx,
        genai.Text("Tell me about this instrument"),
        genai.ImageData("jpeg", imgData))
    if err != nil {
        log.Fatal(err)
    }

    printResponse(resp) // utility for printing response

**After**  

### Python

Many of the same convenience features exist in the new SDK. For
example, `PIL.Image` objects are automatically converted.  

    from google import genai
    from PIL import Image

    client = genai.Client()

    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=[
            'Tell me a story based on this image',
            Image.open(image_path)
        ]
    )
    print(response.text)

### JavaScript

    import {GoogleGenAI} from '@google/genai';

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });

    const organ = await ai.files.upload({
      file: "path/to/organ.jpg",
    });

    const response = await ai.models.generateContent({
      model: "gemini-2.0-flash",
      contents: [
        createUserContent([
          "Tell me a story based on this image",
          createPartFromUri(organ.uri, organ.mimeType)
        ]),
      ],
    });
    console.log(response.text);

### Go

    ctx := context.Background()
    client, err := genai.NewClient(ctx, nil)
    if err != nil {
        log.Fatal(err)
    }

    imgData, err := os.ReadFile("path/to/organ.jpg")
    if err != nil {
        log.Fatal(err)
    }

    parts := []*genai.Part{
        {Text: "Tell me a story based on this image"},
        {InlineData: &genai.Blob{Data: imgData, MIMEType: "image/jpeg"}},
    }
    contents := []*genai.Content{
        {Parts: parts},
    }

    result, err := client.Models.GenerateContent(ctx, "gemini-2.0-flash", contents, nil)
    if err != nil {
        log.Fatal(err)
    }
    debugPrint(result) // utility for printing result

### Streaming

**Before**  

### Python

    import google.generativeai as genai

    response = model.generate_content(
        "Write a cute story about cats.",
        stream=True)
    for chunk in response:
        print(chunk.text)

### JavaScript

    import { GoogleGenerativeAI } from "@google/generative-ai";

    const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY");
    const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });

    const prompt = "Write a story about a magic backpack.";

    const result = await model.generateContentStream(prompt);

    // Print text as it comes in.
    for await (const chunk of result.stream) {
      const chunkText = chunk.text();
      process.stdout.write(chunkText);
    }

### Go

    ctx := context.Background()
    client, err := genai.NewClient(ctx, option.WithAPIKey("GOOGLE_API_KEY"))
    if err != nil {
        log.Fatal(err)
    }
    defer client.Close()

    model := client.GenerativeModel("gemini-1.5-flash")
    iter := model.GenerateContentStream(ctx, genai.Text("Write a story about a magic backpack."))
    for {
        resp, err := iter.Next()
        if err == iterator.Done {
            break
        }
        if err != nil {
            log.Fatal(err)
        }
        printResponse(resp) // utility for printing the response
    }

**After**  

### Python

    from google import genai

    client = genai.Client()

    for chunk in client.models.generate_content_stream(
      model='gemini-2.0-flash',
      contents='Tell me a story in 300 words.'
    ):
        print(chunk.text)

### JavaScript

    import {GoogleGenAI} from '@google/genai';

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });

    const response = await ai.models.generateContentStream({
      model: "gemini-2.0-flash",
      contents: "Write a story about a magic backpack.",
    });
    let text = "";
    for await (const chunk of response) {
      console.log(chunk.text);
      text += chunk.text;
    }

### Go

    ctx := context.Background()
    client, err := genai.NewClient(ctx, nil)
    if err != nil {
        log.Fatal(err)
    }

    for result, err := range client.Models.GenerateContentStream(
        ctx,
        "gemini-2.0-flash",
        genai.Text("Write a story about a magic backpack."),
        nil,
    ) {
        if err != nil {
            log.Fatal(err)
        }
        fmt.Print(result.Candidates[0].Content.Parts[0].Text)
    }

## Configuration

**Before**  

### Python

    import google.generativeai as genai

    model = genai.GenerativeModel(
      'gemini-1.5-flash',
        system_instruction='you are a story teller for kids under 5 years old',
        generation_config=genai.GenerationConfig(
          max_output_tokens=400,
          top_k=2,
          top_p=0.5,
          temperature=0.5,
          response_mime_type='application/json',
          stop_sequences=['\n'],
        )
    )
    response = model.generate_content('tell me a story in 100 words')

### JavaScript

    import { GoogleGenerativeAI } from "@google/generative-ai";

    const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY");
    const model = genAI.getGenerativeModel({
      model: "gemini-1.5-flash",
      generationConfig: {
        candidateCount: 1,
        stopSequences: ["x"],
        maxOutputTokens: 20,
        temperature: 1.0,
      },
    });

    const result = await model.generateContent(
      "Tell me a story about a magic backpack.",
    );
    console.log(result.response.text())

### Go

    ctx := context.Background()
    client, err := genai.NewClient(ctx, option.WithAPIKey("GOOGLE_API_KEY"))
    if err != nil {
        log.Fatal(err)
    }
    defer client.Close()

    model := client.GenerativeModel("gemini-1.5-flash")
    model.SetTemperature(0.5)
    model.SetTopP(0.5)
    model.SetTopK(2.0)
    model.SetMaxOutputTokens(100)
    model.ResponseMIMEType = "application/json"
    resp, err := model.GenerateContent(ctx, genai.Text("Tell me about New York"))
    if err != nil {
        log.Fatal(err)
    }
    printResponse(resp) // utility for printing response

**After**  

### Python

For all methods in the new SDK, the required arguments are provided as
keyword arguments. All optional inputs are provided in the `config`
argument. Config arguments can be specified as either Python dictionaries or
`Config` classes in the `google.genai.types` namespace. For utility and
uniformity, all definitions within the `types` module are `pydantic`
classes.  

    from google import genai
    from google.genai import types

    client = genai.Client()

    response = client.models.generate_content(
      model='gemini-2.0-flash',
      contents='Tell me a story in 100 words.',
      config=types.GenerateContentConfig(
          system_instruction='you are a story teller for kids under 5 years old',
          max_output_tokens= 400,
          top_k= 2,
          top_p= 0.5,
          temperature= 0.5,
          response_mime_type= 'application/json',
          stop_sequences= ['\n'],
          seed=42,
      ),
    )

### JavaScript

    import {GoogleGenAI} from '@google/genai';

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });

    const response = await ai.models.generateContent({
      model: "gemini-2.0-flash",
      contents: "Tell me a story about a magic backpack.",
      config: {
        candidateCount: 1,
        stopSequences: ["x"],
        maxOutputTokens: 20,
        temperature: 1.0,
      },
    });

    console.log(response.text);

### Go

    ctx := context.Background()
    client, err := genai.NewClient(ctx, nil)
    if err != nil {
        log.Fatal(err)
    }

    result, err := client.Models.GenerateContent(ctx,
        "gemini-2.0-flash",
        genai.Text("Tell me about New York"),
        &genai.GenerateContentConfig{
            Temperature:      genai.Ptr[float32](0.5),
            TopP:             genai.Ptr[float32](0.5),
            TopK:             genai.Ptr[float32](2.0),
            ResponseMIMEType: "application/json",
            StopSequences:    []string{"Yankees"},
            CandidateCount:   2,
            Seed:             genai.Ptr[int32](42),
            MaxOutputTokens:  128,
            PresencePenalty:  genai.Ptr[float32](0.5),
            FrequencyPenalty: genai.Ptr[float32](0.5),
        },
    )
    if err != nil {
        log.Fatal(err)
    }
    debugPrint(result) // utility for printing response

## Safety settings

Generate a response with safety settings:

**Before**  

### Python

    import google.generativeai as genai

    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(
        'say something bad',
        safety_settings={
            'HATE': 'BLOCK_ONLY_HIGH',
            'HARASSMENT': 'BLOCK_ONLY_HIGH',
      }
    )

### JavaScript

    import { GoogleGenerativeAI, HarmCategory, HarmBlockThreshold } from "@google/generative-ai";

    const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY");
    const model = genAI.getGenerativeModel({
      model: "gemini-1.5-flash",
      safetySettings: [
        {
          category: HarmCategory.HARM_CATEGORY_HARASSMENT,
          threshold: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        },
      ],
    });

    const unsafePrompt =
      "I support Martians Soccer Club and I think " +
      "Jupiterians Football Club sucks! Write an ironic phrase telling " +
      "them how I feel about them.";

    const result = await model.generateContent(unsafePrompt);

    try {
      result.response.text();
    } catch (e) {
      console.error(e);
      console.log(result.response.candidates[0].safetyRatings);
    }

**After**  

### Python

    from google import genai
    from google.genai import types

    client = genai.Client()

    response = client.models.generate_content(
      model='gemini-2.0-flash',
      contents='say something bad',
      config=types.GenerateContentConfig(
          safety_settings= [
              types.SafetySetting(
                  category='HARM_CATEGORY_HATE_SPEECH',
                  threshold='BLOCK_ONLY_HIGH'
              ),
          ]
      ),
    )

### JavaScript

    import {GoogleGenAI} from '@google/genai';

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });
    const unsafePrompt =
      "I support Martians Soccer Club and I think " +
      "Jupiterians Football Club sucks! Write an ironic phrase telling " +
      "them how I feel about them.";

    const response = await ai.models.generateContent({
      model: "gemini-2.0-flash",
      contents: unsafePrompt,
      config: {
        safetySettings: [
          {
            category: "HARM_CATEGORY_HARASSMENT",
            threshold: "BLOCK_ONLY_HIGH",
          },
        ],
      },
    });

    console.log("Finish reason:", response.candidates[0].finishReason);
    console.log("Safety ratings:", response.candidates[0].safetyRatings);

## Async

**Before**  

### Python

    import google.generativeai as genai

    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content_async(
        'tell me a story in 100 words'
    )

**After**  

### Python

To use the new SDK with `asyncio`, there is a separate `async`
implementation of every method under `client.aio`.  

    from google import genai

    client = genai.Client()

    response = await client.aio.models.generate_content(
        model='gemini-2.0-flash',
        contents='Tell me a story in 300 words.'
    )

## Chat

Start a chat and send a message to the model:

**Before**  

### Python

    import google.generativeai as genai

    model = genai.GenerativeModel('gemini-1.5-flash')
    chat = model.start_chat()

    response = chat.send_message(
        "Tell me a story in 100 words")
    response = chat.send_message(
        "What happened after that?")

### JavaScript

    import { GoogleGenerativeAI } from "@google/generative-ai";

    const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY");
    const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });
    const chat = model.startChat({
      history: [
        {
          role: "user",
          parts: [{ text: "Hello" }],
        },
        {
          role: "model",
          parts: [{ text: "Great to meet you. What would you like to know?" }],
        },
      ],
    });
    let result = await chat.sendMessage("I have 2 dogs in my house.");
    console.log(result.response.text());
    result = await chat.sendMessage("How many paws are in my house?");
    console.log(result.response.text());

### Go

    ctx := context.Background()
    client, err := genai.NewClient(ctx, option.WithAPIKey("GOOGLE_API_KEY"))
    if err != nil {
        log.Fatal(err)
    }
    defer client.Close()

    model := client.GenerativeModel("gemini-1.5-flash")
    cs := model.StartChat()

    cs.History = []*genai.Content{
        {
            Parts: []genai.Part{
                genai.Text("Hello, I have 2 dogs in my house."),
            },
            Role: "user",
        },
        {
            Parts: []genai.Part{
                genai.Text("Great to meet you. What would you like to know?"),
            },
            Role: "model",
        },
    }

    res, err := cs.SendMessage(ctx, genai.Text("How many paws are in my house?"))
    if err != nil {
        log.Fatal(err)
    }
    printResponse(res) // utility for printing the response

**After**  

### Python

    from google import genai

    client = genai.Client()

    chat = client.chats.create(model='gemini-2.0-flash')

    response = chat.send_message(
        message='Tell me a story in 100 words')
    response = chat.send_message(
        message='What happened after that?')

### JavaScript

    import {GoogleGenAI} from '@google/genai';

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });
    const chat = ai.chats.create({
      model: "gemini-2.0-flash",
      history: [
        {
          role: "user",
          parts: [{ text: "Hello" }],
        },
        {
          role: "model",
          parts: [{ text: "Great to meet you. What would you like to know?" }],
        },
      ],
    });

    const response1 = await chat.sendMessage({
      message: "I have 2 dogs in my house.",
    });
    console.log("Chat response 1:", response1.text);

    const response2 = await chat.sendMessage({
      message: "How many paws are in my house?",
    });
    console.log("Chat response 2:", response2.text);

### Go

    ctx := context.Background()
    client, err := genai.NewClient(ctx, nil)
    if err != nil {
        log.Fatal(err)
    }

    chat, err := client.Chats.Create(ctx, "gemini-2.0-flash", nil, nil)
    if err != nil {
        log.Fatal(err)
    }

    result, err := chat.SendMessage(ctx, genai.Part{Text: "Hello, I have 2 dogs in my house."})
    if err != nil {
        log.Fatal(err)
    }
    debugPrint(result) // utility for printing result

    result, err = chat.SendMessage(ctx, genai.Part{Text: "How many paws are in my house?"})
    if err != nil {
        log.Fatal(err)
    }
    debugPrint(result) // utility for printing result

## Function calling

**Before**  

### Python

    import google.generativeai as genai
    from enum import Enum

    def get_current_weather(location: str) -> str:
        """Get the current whether in a given location.

        Args:
            location: required, The city and state, e.g. San Franciso, CA
            unit: celsius or fahrenheit
        """
        print(f'Called with: {location=}')
        return "23C"

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        tools=[get_current_weather]
    )

    response = model.generate_content("What is the weather in San Francisco?")
    function_call = response.candidates[0].parts[0].function_call

**After**  

### Python

In the new SDK, automatic function calling is the default. Here, you disable
it.  

    from google import genai
    from google.genai import types

    client = genai.Client()

    def get_current_weather(location: str) -> str:
        """Get the current whether in a given location.

        Args:
            location: required, The city and state, e.g. San Franciso, CA
            unit: celsius or fahrenheit
        """
        print(f'Called with: {location=}')
        return "23C"

    response = client.models.generate_content(
      model='gemini-2.0-flash',
      contents="What is the weather like in Boston?",
      config=types.GenerateContentConfig(
          tools=[get_current_weather],
          automatic_function_calling={'disable': True},
      ),
    )

    function_call = response.candidates[0].content.parts[0].function_call

### Automatic function calling

**Before**  

### Python

The old SDK only supports automatic function calling in chat. In the new SDK
this is the default behavior in `generate_content`.  

    import google.generativeai as genai

    def get_current_weather(city: str) -> str:
        return "23C"

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        tools=[get_current_weather]
    )

    chat = model.start_chat(
        enable_automatic_function_calling=True)
    result = chat.send_message("What is the weather in San Francisco?")

**After**  

### Python

    from google import genai
    from google.genai import types
    client = genai.Client()

    def get_current_weather(city: str) -> str:
        return "23C"

    response = client.models.generate_content(
      model='gemini-2.0-flash',
      contents="What is the weather like in Boston?",
      config=types.GenerateContentConfig(
          tools=[get_current_weather]
      ),
    )

## Code execution

Code execution is a tool that allows the model to generate Python code, run it,
and return the result.

**Before**  

### Python

    import google.generativeai as genai

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        tools="code_execution"
    )

    result = model.generate_content(
      "What is the sum of the first 50 prime numbers? Generate and run code for "
      "the calculation, and make sure you get all 50.")

### JavaScript

    import { GoogleGenerativeAI } from "@google/generative-ai";

    const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY");
    const model = genAI.getGenerativeModel({
      model: "gemini-1.5-flash",
      tools: [{ codeExecution: {} }],
    });

    const result = await model.generateContent(
      "What is the sum of the first 50 prime numbers? " +
        "Generate and run code for the calculation, and make sure you get " +
        "all 50.",
    );

    console.log(result.response.text());

**After**  

### Python

    from google import genai
    from google.genai import types

    client = genai.Client()

    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents='What is the sum of the first 50 prime numbers? Generate and run '
                'code for the calculation, and make sure you get all 50.',
        config=types.GenerateContentConfig(
            tools=[types.Tool(code_execution=types.ToolCodeExecution)],
        ),
    )

### JavaScript

    import {GoogleGenAI} from '@google/genai';

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });

    const response = await ai.models.generateContent({
      model: "gemini-2.0-pro-exp-02-05",
      contents: `Write and execute code that calculates the sum of the first 50 prime numbers.
                Ensure that only the executable code and its resulting output are generated.`,
    });

    // Each part may contain text, executable code, or an execution result.
    for (const part of response.candidates[0].content.parts) {
      console.log(part);
      console.log("\n");
    }

    console.log("-".repeat(80));
    // The `.text` accessor concatenates the parts into a markdown-formatted text.
    console.log("\n", response.text);

## Search grounding

`GoogleSearch` (Gemini\>=2.0) and `GoogleSearchRetrieval` (Gemini \< 2.0) are
tools that allow the model to retrieve public web data for grounding, powered by
Google.

**Before**  

### Python

    import google.generativeai as genai

    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(
        contents="what is the Google stock price?",
        tools='google_search_retrieval'
    )

**After**  

### Python

    from google import genai
    from google.genai import types

    client = genai.Client()

    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents='What is the Google stock price?',
        config=types.GenerateContentConfig(
            tools=[
                types.Tool(
                    google_search=types.GoogleSearch()
                )
            ]
        )
    )

## JSON response

Generate answers in JSON format.

**Before**  

### Python

By specifying a `response_schema` and setting
`response_mime_type="application/json"` users can constrain the model to
produce a `JSON` response following a given structure.  

    import google.generativeai as genai
    import typing_extensions as typing

    class CountryInfo(typing.TypedDict):
        name: str
        population: int
        capital: str
        continent: str
        major_cities: list[str]
        gdp: int
        official_language: str
        total_area_sq_mi: int

    model = genai.GenerativeModel(model_name="gemini-1.5-flash")
    result = model.generate_content(
        "Give me information of the United States",
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema = CountryInfo
        ),
    )

### JavaScript

    import { GoogleGenerativeAI, SchemaType } from "@google/generative-ai";

    const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY");

    const schema = {
      description: "List of recipes",
      type: SchemaType.ARRAY,
      items: {
        type: SchemaType.OBJECT,
        properties: {
          recipeName: {
            type: SchemaType.STRING,
            description: "Name of the recipe",
            nullable: false,
          },
        },
        required: ["recipeName"],
      },
    };

    const model = genAI.getGenerativeModel({
      model: "gemini-1.5-pro",
      generationConfig: {
        responseMimeType: "application/json",
        responseSchema: schema,
      },
    });

    const result = await model.generateContent(
      "List a few popular cookie recipes.",
    );
    console.log(result.response.text());

**After**  

### Python

The new SDK uses
`pydantic` classes to provide the schema (although you can pass a
`genai.types.Schema`, or equivalent `dict`). When possible, the SDK will
parse the returned JSON, and return the result in `response.parsed`. If you
provided a `pydantic` class as the schema the SDK will convert that `JSON`
to an instance of the class.  

    from google import genai
    from pydantic import BaseModel

    client = genai.Client()

    class CountryInfo(BaseModel):
        name: str
        population: int
        capital: str
        continent: str
        major_cities: list[str]
        gdp: int
        official_language: str
        total_area_sq_mi: int

    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents='Give me information of the United States.',
        config={
            'response_mime_type': 'application/json',
            'response_schema': CountryInfo,
        },
    )

    response.parsed

### JavaScript

    import {GoogleGenAI} from '@google/genai';

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });
    const response = await ai.models.generateContent({
      model: "gemini-2.0-flash",
      contents: "List a few popular cookie recipes.",
      config: {
        responseMimeType: "application/json",
        responseSchema: {
          type: "array",
          items: {
            type: "object",
            properties: {
              recipeName: { type: "string" },
              ingredients: { type: "array", items: { type: "string" } },
            },
            required: ["recipeName", "ingredients"],
          },
        },
      },
    });
    console.log(response.text);

## Files

### Upload

Upload a file:

**Before**  

### Python

    import requests
    import pathlib
    import google.generativeai as genai

    # Download file
    response = requests.get(
        'https://storage.googleapis.com/generativeai-downloads/data/a11.txt')
    pathlib.Path('a11.txt').write_text(response.text)

    file = genai.upload_file(path='a11.txt')

    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content([
        'Can you summarize this file:',
        my_file
    ])
    print(response.text)

**After**  

### Python

    import requests
    import pathlib
    from google import genai

    client = genai.Client()

    # Download file
    response = requests.get(
        'https://storage.googleapis.com/generativeai-downloads/data/a11.txt')
    pathlib.Path('a11.txt').write_text(response.text)

    my_file = client.files.upload(file='a11.txt')

    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=[
            'Can you summarize this file:',
            my_file
        ]
    )
    print(response.text)

### List and get

List uploaded files and get an uploaded file with a filename:

**Before**  

### Python

    import google.generativeai as genai

    for file in genai.list_files():
      print(file.name)

    file = genai.get_file(name=file.name)

**After**  

### Python

    from google import genai
    client = genai.Client()

    for file in client.files.list():
        print(file.name)

    file = client.files.get(name=file.name)

### Delete

Delete a file:

**Before**  

### Python

    import pathlib
    import google.generativeai as genai

    pathlib.Path('dummy.txt').write_text(dummy)
    dummy_file = genai.upload_file(path='dummy.txt')

    file = genai.delete_file(name=dummy_file.name)

**After**  

### Python

    import pathlib
    from google import genai

    client = genai.Client()

    pathlib.Path('dummy.txt').write_text(dummy)
    dummy_file = client.files.upload(file='dummy.txt')

    response = client.files.delete(name=dummy_file.name)

## Context caching

Context caching allows the user to pass the content to the model once, cache the
input tokens, and then refer to the cached tokens in subsequent calls to lower
the cost.

**Before**  

### Python

    import requests
    import pathlib
    import google.generativeai as genai
    from google.generativeai import caching

    # Download file
    response = requests.get(
        'https://storage.googleapis.com/generativeai-downloads/data/a11.txt')
    pathlib.Path('a11.txt').write_text(response.text)

    # Upload file
    document = genai.upload_file(path="a11.txt")

    # Create cache
    apollo_cache = caching.CachedContent.create(
        model="gemini-1.5-flash-001",
        system_instruction="You are an expert at analyzing transcripts.",
        contents=[document],
    )

    # Generate response
    apollo_model = genai.GenerativeModel.from_cached_content(
        cached_content=apollo_cache
    )
    response = apollo_model.generate_content("Find a lighthearted moment from this transcript")

### JavaScript

    import { GoogleAICacheManager, GoogleAIFileManager } from "@google/generative-ai/server";
    import { GoogleGenerativeAI } from "@google/generative-ai";

    const cacheManager = new GoogleAICacheManager("GOOGLE_API_KEY");
    const fileManager = new GoogleAIFileManager("GOOGLE_API_KEY");

    const uploadResult = await fileManager.uploadFile("path/to/a11.txt", {
      mimeType: "text/plain",
    });

    const cacheResult = await cacheManager.create({
      model: "models/gemini-1.5-flash",
      contents: [
        {
          role: "user",
          parts: [
            {
              fileData: {
                fileUri: uploadResult.file.uri,
                mimeType: uploadResult.file.mimeType,
              },
            },
          ],
        },
      ],
    });

    console.log(cacheResult);

    const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY");
    const model = genAI.getGenerativeModelFromCachedContent(cacheResult);
    const result = await model.generateContent(
      "Please summarize this transcript.",
    );
    console.log(result.response.text());

**After**  

### Python

    import requests
    import pathlib
    from google import genai
    from google.genai import types

    client = genai.Client()

    # Check which models support caching.
    for m in client.models.list():
      for action in m.supported_actions:
        if action == "createCachedContent":
          print(m.name)
          break

    # Download file
    response = requests.get(
        'https://storage.googleapis.com/generativeai-downloads/data/a11.txt')
    pathlib.Path('a11.txt').write_text(response.text)

    # Upload file
    document = client.files.upload(file='a11.txt')

    # Create cache
    model='gemini-1.5-flash-001'
    apollo_cache = client.caches.create(
          model=model,
          config={
              'contents': [document],
              'system_instruction': 'You are an expert at analyzing transcripts.',
          },
      )

    # Generate response
    response = client.models.generate_content(
        model=model,
        contents='Find a lighthearted moment from this transcript',
        config=types.GenerateContentConfig(
            cached_content=apollo_cache.name,
        )
    )

### JavaScript

    import {GoogleGenAI} from '@google/genai';

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });
    const filePath = path.join(media, "a11.txt");
    const document = await ai.files.upload({
      file: filePath,
      config: { mimeType: "text/plain" },
    });
    console.log("Uploaded file name:", document.name);
    const modelName = "gemini-1.5-flash";

    const contents = [
      createUserContent(createPartFromUri(document.uri, document.mimeType)),
    ];

    const cache = await ai.caches.create({
      model: modelName,
      config: {
        contents: contents,
        systemInstruction: "You are an expert analyzing transcripts.",
      },
    });
    console.log("Cache created:", cache);

    const response = await ai.models.generateContent({
      model: modelName,
      contents: "Please summarize this transcript",
      config: { cachedContent: cache.name },
    });
    console.log("Response text:", response.text);

## Count tokens

Count the number of tokens in a request.

**Before**  

### Python

    import google.generativeai as genai

    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.count_tokens(
        'The quick brown fox jumps over the lazy dog.')

### JavaScript

     import { GoogleGenerativeAI } from "@google/generative-ai";

     const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY+);
     const model = genAI.getGenerativeModel({
       model: "gemini-1.5-flash",
     });

     // Count tokens in a prompt without calling text generation.
     const countResult = await model.countTokens(
       "The quick brown fox jumps over the lazy dog.",
     );

     console.log(countResult.totalTokens); // 11

     const generateResult = await model.generateContent(
       "The quick brown fox jumps over the lazy dog.",
     );

     // On the response for `generateContent`, use `usageMetadata`
     // to get separate input and output token counts
     // (`promptTokenCount` and `candidatesTokenCount`, respectively),
     // as well as the combined token count (`totalTokenCount`).
     console.log(generateResult.response.usageMetadata);
     // candidatesTokenCount and totalTokenCount depend on response, may vary
     // { promptTokenCount: 11, candidatesTokenCount: 124, totalTokenCount: 135 }

**After**  

### Python

    from google import genai

    client = genai.Client()

    response = client.models.count_tokens(
        model='gemini-2.0-flash',
        contents='The quick brown fox jumps over the lazy dog.',
    )

### JavaScript

    import {GoogleGenAI} from '@google/genai';

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });
    const prompt = "The quick brown fox jumps over the lazy dog.";
    const countTokensResponse = await ai.models.countTokens({
      model: "gemini-2.0-flash",
      contents: prompt,
    });
    console.log(countTokensResponse.totalTokens);

    const generateResponse = await ai.models.generateContent({
      model: "gemini-2.0-flash",
      contents: prompt,
    });
    console.log(generateResponse.usageMetadata);

## Generate images

Generate images:

**Before**  

### Python

    #pip install https://github.com/google-gemini/generative-ai-python@imagen
    import google.generativeai as genai

    imagen = genai.ImageGenerationModel(
        "imagen-3.0-generate-001")
    gen_images = imagen.generate_images(
        prompt="Robot holding a red skateboard",
        number_of_images=1,
        safety_filter_level="block_low_and_above",
        person_generation="allow_adult",
        aspect_ratio="3:4",
    )

**After**  

### Python

    from google import genai

    client = genai.Client()

    gen_images = client.models.generate_images(
        model='imagen-3.0-generate-001',
        prompt='Robot holding a red skateboard',
        config=types.GenerateImagesConfig(
            number_of_images= 1,
            safety_filter_level= "BLOCK_LOW_AND_ABOVE",
            person_generation= "ALLOW_ADULT",
            aspect_ratio= "3:4",
        )
    )

    for n, image in enumerate(gen_images.generated_images):
        pathlib.Path(f'{n}.png').write_bytes(
            image.image.image_bytes)

## Embed content

Generate content embeddings.

**Before**  

### Python

    import google.generativeai as genai

    response = genai.embed_content(
      model='models/gemini-embedding-001',
      content='Hello world'
    )

### JavaScript

    import { GoogleGenerativeAI } from "@google/generative-ai";

    const genAI = new GoogleGenerativeAI("GOOGLE_API_KEY");
    const model = genAI.getGenerativeModel({
      model: "gemini-embedding-001",
    });

    const result = await model.embedContent("Hello world!");

    console.log(result.embedding);

**After**  

### Python

    from google import genai

    client = genai.Client()

    response = client.models.embed_content(
      model='gemini-embedding-001',
      contents='Hello world',
    )

### JavaScript

    import {GoogleGenAI} from '@google/genai';

    const ai = new GoogleGenAI({ apiKey: "GOOGLE_API_KEY" });
    const text = "Hello World!";
    const result = await ai.models.embedContent({
      model: "gemini-embedding-001",
      contents: text,
      config: { outputDimensionality: 10 },
    });
    console.log(result.embeddings);

## Tune a Model

Create and use a tuned model.

The new SDK simplifies tuning with `client.tunings.tune`, which launches the
tuning job and polls until the job is complete.

**Before**  

### Python

    import google.generativeai as genai
    import random

    # create tuning model
    train_data = {}
    for i in range(1, 6):
      key = f'input {i}'
      value = f'output {i}'
      train_data[key] = value

    name = f'generate-num-{random.randint(0,10000)}'
    operation = genai.create_tuned_model(
        source_model='models/gemini-1.5-flash-001-tuning',
        training_data=train_data,
        id = name,
        epoch_count = 5,
        batch_size=4,
        learning_rate=0.001,
    )
    # wait for tuning complete
    tuningProgress = operation.result()

    # generate content with the tuned model
    model = genai.GenerativeModel(model_name=f'tunedModels/{name}')
    response = model.generate_content('55')

**After**  

### Python

    from google import genai
    from google.genai import types

    client = genai.Client()

    # Check which models are available for tuning.
    for m in client.models.list():
      for action in m.supported_actions:
        if action == "createTunedModel":
          print(m.name)
          break

    # create tuning model
    training_dataset=types.TuningDataset(
            examples=[
                types.TuningExample(
                    text_input=f'input {i}',
                    output=f'output {i}',
                )
                for i in range(5)
            ],
        )
    tuning_job = client.tunings.tune(
        base_model='models/gemini-1.5-flash-001-tuning',
        training_dataset=training_dataset,
        config=types.CreateTuningJobConfig(
            epoch_count= 5,
            batch_size=4,
            learning_rate=0.001,
            tuned_model_display_name="test tuned model"
        )
    )

    # generate content with the tuned model
    response = client.models.generate_content(
        model=tuning_job.tuned_model.model,
        contents='55',
    )