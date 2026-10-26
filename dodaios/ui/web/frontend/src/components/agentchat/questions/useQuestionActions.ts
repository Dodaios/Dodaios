import { useCallback, useRef } from "react";
import { AgentChatApiError, type QuestionSubmitAnswer } from "@/lib/agentChatApi";
import { useAgentChatApi } from "../AgentChatStoreContext";
import type { QuestionAnswerState, QuestionState } from "../reduce";
import { patchQuestionDraft, readQuestionDraft, type QuestionRequest } from "./questionDraftStore";
import { localAsAnswer, recommendationOf, seriesPayload, type LocalAnswer } from "./questionModel";

/** At most one "still answering" ping per this many milliseconds. */
export const TOUCH_EVERY_MS = 20_000;

/**
 * What a question card sends, optimistically.
 *
 * The card settles the moment the person answers; the request runs behind
 * it. A failure reopens the card where it was, with the error and the exact
 * request ready to try again. A card the server already closed (its window
 * ran out, the turn ended) is not a failure: its closing event tells the
 * truth, so the optimistic answer just gives way.
 */
export function useQuestionActions(question: QuestionState) {
  const store = useAgentChatApi();
  const { questionId } = question;
  const lastTouch = useRef(0);
  const live = useRef(question);
  live.current = question;

  const run = useCallback(async (request: QuestionRequest) => {
    const state = store.getState();
    if (request.kind === "decide_all") {
      await state.skipQuestion(questionId);
      return;
    }
    if (state.submitQuestion) {
      await state.submitQuestion(questionId, request.answers);
      return;
    }
    // A store without the reviewed submit gets the answers one by one.
    for (const [index, answer] of request.answers.entries()) {
      if (live.current.answers[index]) continue;
      if ("skip" in answer) await state.skipQuestion(questionId, index);
      else if ("option_index" in answer) await state.answerQuestion(questionId, index, { optionIndex: answer.option_index });
      else if ("option_indices" in answer) {
        await state.answerQuestion(questionId, index, { optionIndices: answer.option_indices, text: answer.text });
      } else await state.answerQuestion(questionId, index, { text: "text" in answer ? answer.text ?? "" : "" });
    }
  }, [store, questionId]);

  const send = useCallback(async (request: QuestionRequest, answers: (QuestionAnswerState | null)[]) => {
    if (readQuestionDraft(questionId).submission?.status === "sending") return;
    patchQuestionDraft(questionId, (draft) => ({ ...draft, submission: { status: "sending", request, answers } }));
    try {
      await run(request);
      patchQuestionDraft(questionId, (draft) =>
        draft.submission ? { ...draft, submission: { ...draft.submission, status: "sent" } } : draft);
    } catch (err) {
      if (err instanceof AgentChatApiError && (err.status === 404 || err.status === 410)) {
        patchQuestionDraft(questionId, (draft) => ({ ...draft, submission: null }));
        return;
      }
      const error = err instanceof Error ? err.message : String(err);
      patchQuestionDraft(questionId, (draft) =>
        draft.submission ? { ...draft, submission: { ...draft.submission, status: "failed", error } } : draft);
    }
  }, [questionId, run]);

  /** Send every answer of the card (a lone question is a series of one). */
  const submit = useCallback((locals: LocalAnswer[]) => {
    const q = live.current;
    const answers: QuestionSubmitAnswer[] = seriesPayload(q, locals);
    const shown = q.questions.map((item, i) => q.answers[i] ?? localAsAnswer(locals[i], item));
    return send({ kind: "submit", answers }, shown);
  }, [send]);

  /** Leave every open question to the agent: its recommendations apply. */
  const decideAll = useCallback(() => {
    const q = live.current;
    const shown = q.questions.map((item, i) => q.answers[i] ?? recommendationOf(item, "skipped"));
    return send({ kind: "decide_all" }, shown);
  }, [send]);

  /** Replay the exact request that failed. */
  const retry = useCallback(() => {
    const failed = readQuestionDraft(questionId).submission;
    if (failed?.status === "failed") return send(failed.request, failed.answers);
    return Promise.resolve();
  }, [questionId, send]);

  /** The person is working on the card: keep a live card from timing out under them. */
  const touch = useCallback(() => {
    const q = live.current;
    if (q.deferred || q.closed) return;
    const now = Date.now();
    if (now - lastTouch.current < TOUCH_EVERY_MS) return;
    lastTouch.current = now;
    void store.getState().touchQuestion?.(questionId);
  }, [store, questionId]);

  return { submit, decideAll, retry, touch };
}
