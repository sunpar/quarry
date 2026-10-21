import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  onError: (error: Error) => void;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, _info: ErrorInfo): void {
    this.props.onError(error);
  }

  render(): ReactNode {
    if (this.state.error !== null) {
      return (
        <pre className="m-4 whitespace-pre-wrap font-mono text-sm text-destructive">
          {this.state.error.message}
        </pre>
      );
    }
    return this.props.children;
  }
}
