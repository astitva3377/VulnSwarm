from abc import ABC, abstractmethod
from pathlib import Path
from app.config import EmbedderConfig


class EmbeddingProviderException(Exception):
	def __init__(self, msg: str) -> None:
		super().__init__(msg)



class EmbeddingProvider(ABC):
	def __init__(self, type: str) -> None:
		super().__init__()
		self._type = type
		
	@property
	@abstractmethod
	def get_dimension(self) -> int:
		pass

	@property
	@abstractmethod
	def get_model_name(self) -> str:
		pass

	@abstractmethod
	def embed(self, texts: list[str]) -> list[list[float]]:
		pass



class LocalProvider(EmbeddingProvider):

	def __init__(
		self,
		model_name: str,
		device: str,
		hf_home : Path | None,
		batch_size: int = 16,
		show_progress: bool = False,
		dimensions: int | None = None
	) -> None:
		super().__init__('Local Transformer')
		if hf_home:
			hf_home.mkdir(parents=True, exist_ok=True)
		from sentence_transformers import SentenceTransformer
		self.model_name = model_name
		self.model = SentenceTransformer(
			model_name,
			trust_remote_code=True,
			device=device,
			cache_folder=str(hf_home.resolve()) if hf_home else None
		)
		self.dimensions = dimensions or self.model.get_sentence_embedding_dimension()
		self.batch_size = batch_size
		self.show_progress = show_progress

	@property
	def get_model_name(self) -> str:
		return self.model_name

	@property
	def get_dimension(self) -> int:
		if self.dimensions:
			return self.dimensions
		else:
			raise EmbeddingProviderException(msg='Unknown dimensions for configured embedding model')

	def embed(self, texts: list[str]) -> list[list[float]]:
		if not texts:
			return []
		vectors = self.model.encode(
			texts, batch_size=self.batch_size,
			show_progress_bar=self.show_progress,
			convert_to_numpy=True
		)
		return vectors.tolist()


class OpenAICompatibleProvider(EmbeddingProvider):

	def __init__(
		self,
		model_name: str,
		base_url: str,
		api_key: str | None,
		batch_size: int = 16,
		show_progress: bool = False,
		dimensions: int | None = None
	) -> None:
		super().__init__('OpenAI')
		from openai import OpenAI
		self.model_name = model_name
		self.client = OpenAI(
			base_url=base_url,
			api_key=api_key if api_key else 'lmstudio'
		)
		self.batch_size = batch_size
		self.show_progress = show_progress
		self.dimensions = dimensions

	@property
	def get_model_name(self) -> str:
		return self.model_name

	@property
	def get_dimension(self) -> int:
		if self.dimensions:
			return self.dimensions
		else:
			self.dimensions = len(self.embed(['a'])[0])
			return self.dimensions

	def embed(self, texts: list[str]) -> list[list[float]]:
		if not texts:
			return []
		response = self.client.embeddings.create(
			model=self.model_name, input=texts
		)
		vectors = [item.embedding for item in response.data]

		return vectors



class EmbeddingProviderFactory:

	@staticmethod
	def get_provider(
		config: EmbedderConfig,
		batch_size: int = 16,
		show_progress: bool = False,
	) -> EmbeddingProvider:
		if config.provider is None or config.provider.lower() == 'local':
			return LocalProvider(
				model_name=config.model,
				device=config.device,
				batch_size=batch_size,
				show_progress=show_progress,
				dimensions=config.dimensions,
				hf_home=config.hf_home
			)
		elif config.provider.lower() in ['openai', 'open-ai', 'lmstudio', 'lm-studio']:
			if config.base_url is None:
				raise EmbeddingProviderException(f'OpenAI compliant embedder needs URL but provided is None')
			return OpenAICompatibleProvider(
				model_name=config.model,
				base_url=config.base_url,
				api_key=config.api_key,
				batch_size=batch_size,
				show_progress=show_progress,
				dimensions=config.dimensions
			)
		else:
			raise EmbeddingProviderException(f'Unknown provider: {config.provider}')
