"""Writes the IEEE reference list straight into main.tex (no BibTeX needed).

Entries are numbered in order of first citation, as IEEE requires. Author
lists follow the SSRC template: every author is listed; lists longer than 15
are cut after six names with "et al." as in the template's example [b50].
Author lists were checked against the arXiv API / publisher records on
2026-11-08. Usage: python make_bib.py   (run inside docs/paper)
"""
import re

REFS = {
    "lewis2020rag": r"P. Lewis, E. Perez, A. Piktus, F. Petroni, V. Karpukhin, N. Goyal, H. K\"{u}ttler, M. Lewis, W.-t. Yih, T. Rockt\"{a}schel, S. Riedel, and D. Kiela, ``Retrieval-augmented generation for knowledge-intensive NLP tasks,'' in \textit{Proc. Adv. Neural Inf. Process. Syst. (NeurIPS)}, vol. 33, 2020. arXiv:2005.11401.",
    "gao2023ragsurvey": r"Y. Gao, Y. Xiong, X. Gao, K. Jia, J. Pan, Y. Bi, Y. Dai, J. Sun, M. Wang, and H. Wang, ``Retrieval-augmented generation for large language models: A survey,'' 2023, arXiv:2312.10997.",
    "asai2024selfrag": r"A. Asai, Z. Wu, Y. Wang, A. Sil, and H. Hajishirzi, ``Self-RAG: Learning to retrieve, generate, and critique through self-reflection,'' in \textit{Proc. Int. Conf. Learn. Represent. (ICLR)}, 2024. arXiv:2310.11511.",
    "yan2024crag": r"S.-Q. Yan, J.-C. Gu, Y. Zhu, and Z.-H. Ling, ``Corrective retrieval augmented generation,'' 2024, arXiv:2401.15884.",
    "singh2025agenticrag": r"A. Singh, A. Ehtesham, S. Kumar, T. T. Khoei, and A. V. Vasilakos, ``Agentic retrieval-augmented generation: A survey on agentic RAG,'' 2025, arXiv:2501.09136.",
    "yao2023react": r"S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan, and Y. Cao, ``ReAct: Synergizing reasoning and acting in language models,'' in \textit{Proc. Int. Conf. Learn. Represent. (ICLR)}, 2023. arXiv:2210.03629.",
    "schick2023toolformer": r"T. Schick, J. Dwivedi-Yu, R. Dess\`{\i}, R. Raileanu, M. Lomeli, L. Zettlemoyer, N. Cancedda, and T. Scialom, ``Toolformer: Language models can teach themselves to use tools,'' in \textit{Proc. Adv. Neural Inf. Process. Syst. (NeurIPS)}, vol. 36, 2023. arXiv:2302.04761.",
    "wu2023autogen": r"Q. Wu, G. Bansal, J. Zhang, Y. Wu, B. Li, E. Zhu, L. Jiang, X. Zhang, S. Zhang, J. Liu, A. H. Awadallah, R. W. White, D. Burger, and C. Wang, ``AutoGen: Enabling next-gen LLM applications via multi-agent conversation,'' 2023, arXiv:2308.08155.",
    "hong2024metagpt": r"S. Hong, M. Zhuge, J. Chen, X. Zheng, Y. Cheng, C. Zhang, J. Wang, Z. Wang, S. K. S. Yau, Z. Lin, L. Zhou, C. Ran, L. Xiao, C. Wu, and J. Schmidhuber, ``MetaGPT: Meta programming for a multi-agent collaborative framework,'' in \textit{Proc. Int. Conf. Learn. Represent. (ICLR)}, 2024. arXiv:2308.00352.",
    "guo2024multiagent": r"T. Guo, X. Chen, Y. Wang, R. Chang, S. Pei, N. V. Chawla, O. Wiest, and X. Zhang, ``Large language model based multi-agents: A survey of progress and challenges,'' in \textit{Proc. 33rd Int. Joint Conf. Artif. Intell. (IJCAI)}, Jeju, South Korea, 2024, pp. 8048--8057, doi: 10.24963/ijcai.2024/890.",
    "wang2024agentsurvey": r"L. Wang, C. Ma, X. Feng, Z. Zhang, H. Yang, J. Zhang, Z. Chen, J. Tang, X. Chen, Y. Lin, W. X. Zhao, Z. Wei, and J.-R. Wen, ``A survey on large language model based autonomous agents,'' \textit{Front. Comput. Sci.}, vol. 18, no. 6, Dec. 2024, Art. no. 186345, doi: 10.1007/s11704-024-40231-1.",
    "yao2022webshop": r"S. Yao, H. Chen, J. Yang, and K. Narasimhan, ``WebShop: Towards scalable real-world web interaction with grounded language agents,'' in \textit{Proc. Adv. Neural Inf. Process. Syst. (NeurIPS)}, vol. 35, 2022. arXiv:2207.01206.",
    "yao2024taubench": r"S. Yao, N. Shinn, P. Razavi, and K. Narasimhan, ``$\tau$-bench: A benchmark for tool-agent-user interaction in real-world domains,'' 2024, arXiv:2406.12045.",
    "jin2024shoppingmmlu": r"Y. Jin, Z. Li, C. Zhang, T. Cao, Y. Gao, P. Jayarao, \textit{et al.}, ``Shopping MMLU: A massive multi-task online shopping benchmark for large language models,'' in \textit{Proc. Adv. Neural Inf. Process. Syst. (NeurIPS), Datasets Benchmarks Track}, 2024. arXiv:2410.20745.",
    "peng2024ecellm": r"B. Peng, X. Ling, Z. Chen, H. Sun, and X. Ning, ``eCeLLM: Generalizing large language models for e-commerce from large-scale, high-quality instruction data,'' in \textit{Proc. 41st Int. Conf. Mach. Learn. (ICML)}, Vienna, Austria, 2024. arXiv:2402.08831.",
    "greshake2023injection": r"K. Greshake, S. Abdelnabi, S. Mishra, C. Endres, T. Holz, and M. Fritz, ``Not what you've signed up for: Compromising real-world LLM-integrated applications with indirect prompt injection,'' in \textit{Proc. 16th ACM Workshop Artif. Intell. Secur. (AISec)}, Copenhagen, Denmark, 2023, pp. 79--90, doi: 10.1145/3605764.3623985.",
    "debenedetti2024agentdojo": r"E. Debenedetti, J. Zhang, M. Balunovi\'{c}, L. Beurer-Kellner, M. Fischer, and F. Tram\`{e}r, ``AgentDojo: A dynamic environment to evaluate prompt injection attacks and defenses for LLM agents,'' in \textit{Proc. Adv. Neural Inf. Process. Syst. (NeurIPS), Datasets Benchmarks Track}, 2024. arXiv:2406.13352.",
    "ruan2024toolemu": r"Y. Ruan, H. Dong, A. Wang, S. Pitis, Y. Zhou, J. Ba, Y. Dubois, C. J. Maddison, and T. Hashimoto, ``Identifying the risks of LM agents with an LM-emulated sandbox,'' in \textit{Proc. Int. Conf. Learn. Represent. (ICLR)}, 2024. arXiv:2309.15817.",
    "huang2025hallucination": r"L. Huang, W. Yu, W. Ma, W. Zhong, Z. Feng, H. Wang, Q. Chen, W. Peng, X. Feng, B. Qin, and T. Liu, ``A survey on hallucination in large language models: Principles, taxonomy, challenges, and open questions,'' \textit{ACM Trans. Inf. Syst.}, vol. 43, no. 2, 2025, doi: 10.1145/3703155.",
    "zheng2023judge": r"L. Zheng, W.-L. Chiang, Y. Sheng, S. Zhuang, Z. Wu, Y. Zhuang, Z. Lin, Z. Li, D. Li, E. P. Xing, H. Zhang, J. E. Gonzalez, and I. Stoica, ``Judging LLM-as-a-judge with MT-Bench and Chatbot Arena,'' in \textit{Proc. Adv. Neural Inf. Process. Syst. (NeurIPS), Datasets Benchmarks Track}, 2023. arXiv:2306.05685.",
    "garciamolina1987sagas": r"H. Garcia-Molina and K. Salem, ``Sagas,'' in \textit{Proc. ACM SIGMOD Int. Conf. Manage. Data}, San Francisco, CA, USA, 1987, pp. 249--259, doi: 10.1145/38713.38742.",
    "helland2012idempotence": r"P. Helland, ``Idempotence is not a medical condition,'' \textit{ACM Queue}, vol. 10, no. 4, p. 30, Apr. 2012. [Online]. Available: \underline{https://queue.acm.org/detail.cfm?id=2187821}. Accessed on: Nov. 8, 2026.",
    "richardson2018microservices": r"C. Richardson, \textit{Microservices Patterns: With Examples in Java}. Shelter Island, NY, USA: Manning, 2018.",
    "robertson2009bm25": r"S. Robertson and H. Zaragoza, ``The probabilistic relevance framework: BM25 and beyond,'' \textit{Found. Trends Inf. Retr.}, vol. 3, no. 4, pp. 333--389, Dec. 2009, doi: 10.1561/1500000019.",
    "cormack2009rrf": r"G. V. Cormack, C. L. A. Clarke, and S. B\"{u}ttcher, ``Reciprocal rank fusion outperforms Condorcet and individual rank learning methods,'' in \textit{Proc. 32nd Int. ACM SIGIR Conf. Res. Develop. Inf. Retr.}, Boston, MA, USA, 2009, pp. 758--759, doi: 10.1145/1571941.1572114.",
    "nogueira2019rerank": r"R. Nogueira and K. Cho, ``Passage re-ranking with BERT,'' 2019, arXiv:1901.04085.",
    "bonifacio2021mmarco": r"L. Bonifacio, V. Jeronymo, H. Q. Abonizio, I. Campiotti, M. Fadaee, R. Lotufo, and R. Nogueira, ``mMARCO: A multilingual version of the MS MARCO passage ranking dataset,'' 2021, arXiv:2108.13897.",
    "lee2025geminiembedding": r"J. Lee, F. Chen, S. Dua, D. Cer, M. Shanbhogue, I. Naim, \textit{et al.}, ``Gemini Embedding: Generalizable embeddings from Gemini,'' 2025, arXiv:2503.07891.",
    "kreps2011kafka": r"J. Kreps, N. Narkhede, and J. Rao, ``Kafka: A distributed messaging system for log processing,'' in \textit{Proc. 6th Int. Workshop Netw. Meets Databases (NetDB)}, Athens, Greece, 2011.",
    "langgraph": r"LangChain, ``LangGraph: Build resilient language agents as graphs,'' Software. [Online]. Available: \underline{https://github.com/langchain-ai/langgraph}. Accessed on: Nov. 8, 2026.",
    "qdrant": r"Qdrant, ``Qdrant: Vector search engine and vector database,'' Software. [Online]. Available: \underline{https://github.com/qdrant/qdrant}. Accessed on: Nov. 8, 2026.",
}

tex = open("main.tex", encoding="utf-8").read()
body = tex.split(r"\begin{thebibliography}")[0]
order = []
for group in re.findall(r"\\cite\{([^}]*)\}", body):
    for key in (k.strip() for k in group.split(",")):
        if key not in order:
            order.append(key)
missing = [k for k in order if k not in REFS]
unused = [k for k in REFS if k not in order]
assert not missing, f"cited but not in REFS: {missing}"

items = "\n".join(rf"\bibitem{{{key}}} {REFS[key]}" for key in order)
block = "\\begin{thebibliography}{00}\n" + items + "\n\\end{thebibliography}"
pattern = re.compile(r"\\bibliographystyle\{IEEEtran\}\s*\\bibliography\{refs\}|\\begin\{thebibliography\}.*?\\end\{thebibliography\}", re.S)
assert pattern.search(tex), "no bibliography block found"
tex = pattern.sub(lambda _m: block, tex, count=1)
open("main.tex", "w", encoding="utf-8", newline="\n").write(tex)
print(f"{len(order)} references written; unused in REFS: {unused}")
