import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  onError: (error: Error) => void;
  resetKey: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
  resetKey: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(
    props: Props,
    state: State,
  ): Partial<State> | null {
    return props.resetKey === state.resetKey
      ? null
      : { error: null, resetKey: props.resetKey };
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
