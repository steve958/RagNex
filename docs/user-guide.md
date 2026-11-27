# User guide

How to use RagNex in the browser: upload your documents, then ask questions and get answers
that cite them. For connecting other programs, see the [API guide](api.md). If something
doesn't work, see [Troubleshooting](troubleshooting.md).

## Getting started

1. **Create an account.** Open RagNex and choose **Register**. You get a workspace of your
   own: everything you add lives there. If there's no Register link, sign-up is closed on
   your server; ask its administrator for an account.
2. **Create a knowledge base.** On the dashboard, choose **New knowledge base**, give it a
   name, and pick a template (see [Templates](#templates); **General** suits most documents).
3. **Upload a document.** Open the knowledge base and upload a file. Its status moves from
   `pending` through `parsing` and `indexing` to `indexed`. Small files take seconds; long
   PDFs can take minutes.
4. **Ask a question.** Go to **Chat**, tick the knowledge bases to use, choose **New**, and
   type your question. Press **Send** or Ctrl+Enter. The answer appears as it's written, and
   **citations** under it show which passages it used.

## Knowledge bases

A knowledge base is a collection of documents that are searched together. You might have
one per project, team or subject. A chat can draw on several at once.

On a knowledge base's page you can upload documents, see their status, and open one to
inspect it. Its **Settings** page lets you rename it, change its description or template,
and delete it. Deleting a knowledge base deletes its documents too.

### Templates

The template decides how documents are cut into passages ("chunks") before they're indexed.
Answers are built from the passages that best match a question, so the cut matters.

| Template | For | How it cuts |
|---|---|---|
| **General** | Most documents: reports, manuals, notes, web pages | Into passages of about 512 tokens, at sentence and line breaks |
| **Laws** | Legislation, regulations, contracts, policies: anything with numbered articles and clauses | Along the document's numbered structure (chapters, articles, clauses), so a passage keeps the heading it belongs to |
| **Paper** | Academic and technical papers | Keeps the abstract as one passage, then cuts by section (Introduction, Methods, Results…), so a passage doesn't mix sections |

The template is applied when a document is processed. Changing it later affects documents
uploaded afterwards; to re-cut existing ones, reprocess them (see below).

## Documents

### Supported files

PDF, Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx`), CSV, HTML, Markdown, plain text
and JSON (`.json`, `.jsonl`). Two-column PDFs, such as papers and official gazettes, are read
column by column. The older Office formats (`.doc`, `.ppt`, `.xls`) aren't
supported: save them in the newer format first. PDFs need to contain text; scanned PDFs
(images of pages) only work if your server has OCR enabled.

The largest file accepted is set by the administrator (100 MB by default).

### Statuses

| Status | Meaning |
|---|---|
| `pending` | Waiting to be processed. |
| `parsing` | Text is being extracted. |
| `done` | Text extracted; waiting to be indexed. |
| `indexing` | Passages are being prepared for search. |
| `indexed` | Ready: it can be searched and used in answers. |
| `failed` | Something went wrong; the list shows why. |

The list refreshes by itself while anything is being processed.

### Actions

- **Open** a document (click its name) to see its progress and its passages. You can
  search within the passages and open one to read it in full.
- **Download** gives you the original file, exactly as it was uploaded.
- **Reprocess** runs a failed document through processing again, for example after the
  administrator fixed what made it fail. **Reprocess N failed** does that for all failed
  documents in the knowledge base.
- **Delete** removes the document and everything made from it. It disappears from search
  and answers at once.

## Chat

On the **Chat** page:

- **Start a chat:** tick the knowledge bases to draw on, then choose **New**. Each chat
  keeps the knowledge bases it was created with.
- **Ask:** type your question and press **Send** or Ctrl+Enter. Follow-up questions can
  refer to earlier ones ("and what about 2023?"): recent messages are taken into account.
  In long chats, the earlier part is kept as a summary, so the model still knows what the
  conversation was about, though not every detail of it.
- **Citations:** an answer that used your documents shows how many passages it cited.
  Click to open the passage; from there, **Download original** gets the source document.
- **History:** chats are saved. Pick one from the list to continue it, or delete it.

If you close the page while an answer is being written, it's still finished and saved; it
shows up when you open the chat again.

Answers are only as good as what the documents contain and what the search finds. If an
answer misses something you know is there, try asking more specifically, using the words
the document uses.

## Settings

### Models

The **LLM** tab sets the model that writes answers (Ollama, OpenAI, vLLM or Anthropic's
Claude); the **Embeddings** tab sets the model that prepares documents and questions for
search. Both are set by the server
administrator; workspace owners can override them for their workspace. Members can see the
settings but not change them.

- An empty field uses the server's default, shown greyed out.
- **API key:** needed when the workspace uses a provider (such as OpenAI) with its own
  account. Stored keys are never shown again; enter a new one to replace it. If Settings
  says the stored key can't be read any more, the server's encryption key changed: enter
  the key again.
- **Embedding model:** can only be changed while the workspace has no processed documents,
  because documents prepared with different models can't be searched together.

### API keys

API keys let other programs use your workspace without your password; see the
[API guide](api.md). Choose what a key may do:

- **read**: search, chat history, listing and downloading documents;
- **write**: everything a member can do, including uploading, deleting and chatting.

The key is shown **once**, when it's created: copy it then. Revoke a key as soon as it's no
longer needed or may have leaked.

### Workspace

Shows who's in the current workspace. Owners can:

- **add people** by their email address, as a member or an owner. They need an account
  already (sign-up, or ask the administrator);
- **change someone's role** or **remove** them. A workspace always keeps at least one
  owner, so the last owner can't be demoted or removed.

Members see the list but can't change it. Owners can also change model settings and API
keys; members can use the workspace's knowledge bases and chat.

Below that are all the workspaces you belong to. Switch between them here or with the
workspace menu at the top of the page (it appears once you belong to more than one), and
create new ones. Each workspace has its own knowledge bases, documents and chats.
