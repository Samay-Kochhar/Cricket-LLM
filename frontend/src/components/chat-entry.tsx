"use client";

import { FormEvent, useEffect, useState } from "react";


type ChatEntryProps = {
  defaultValue: string;
  isLoading?: boolean;
  onSubmit: (question: string) => void;
};


const SUGGESTED_PROMPTS = [
  "Is Virat Kohli better at number 3 or opening in ODIs?",
  "Where does Hardik Pandya score the most and on which shots?",
  "Has Shimron Hetmyer become more destructive over time?",
];


export function ChatEntry({ defaultValue, isLoading = false, onSubmit }: ChatEntryProps) {
  const [value, setValue] = useState(defaultValue);

  useEffect(() => {
    setValue(defaultValue);
  }, [defaultValue]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) {
      return;
    }
    onSubmit(trimmed);
  }

  return (
    <form className="chat-entry" onSubmit={handleSubmit}>
      <textarea
        disabled={isLoading}
        name="question"
        onChange={(event) => setValue(event.target.value)}
        placeholder="Ask an ODI analysis question..."
        value={value}
      />
      <div className="chip-row">
        {SUGGESTED_PROMPTS.map((prompt) => (
          <button
            className="ghost-button"
            key={prompt}
            onClick={() => setValue(prompt)}
            disabled={isLoading}
            type="button"
          >
            Use prompt
          </button>
        ))}
      </div>
      <div>
        <button className="primary-button" disabled={isLoading} type="submit">
          {isLoading ? "Running..." : "Run ODI Query"}
        </button>
      </div>
    </form>
  );
}
